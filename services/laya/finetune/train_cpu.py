"""Fine-tune Laya's multilingual checkpoint on the Mapay news set, on CPU (#47).

    python services/laya/finetune/train_cpu.py [OUTPUT_DIR]     # default $LAYA_DATA_DIR/laya-mapay

A single-process version of the training script in Laya's Kaggle notebook
(notebooks/laya_finetune_typed_decisions_2xT4_kaggle.ipynb, Copyright ConvAI Innovations,
Apache License 2.0): the same RLCD objective (GRPO-style policy gradient on a proper scoring rule
plus soft cross-entropy), learning rates, schedule and post-training temperature calibration on a
held-out slice. Changes: no DDP / CUDA / fp16 (plain fp32 on CPU), short sequences (news titles),
and our train.jsonl instead of LocalLLaMA/typed-decisions. mapay_finetune.ipynb is the GPU path.
"""
import json
import os
import random
import sys
import time
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from safetensors.torch import load_file, save_file
from transformers import AutoTokenizer

from laya.agent import _fix_tokenizer_config
from laya.common import QTYPES, build_model, build_sequence, proper_reward, render_options

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR  # noqa: E402

BASE_REPO, BASE_SUBFOLDER = "convaiinnovations/laya", "multilingual"
EPOCHS = int(os.environ.get("EPOCHS", 4))
MICRO_BATCH, GRAD_ACCUM, GROUP_SIZE = 8, 4, 4
LR_ENCODER, LR_HEAD = 2.5e-5, 1.0e-4
SIGMA_START, SIGMA_END = 0.4, 0.1
MAX_LEN, HEAD_MAX_LEN = 256, 192


def training_item(tok, cfg, state, q, gold_q):
    t, crit = q["type"], q.get("criteria", {})
    probs = gold_q["probabilities"]
    if t == "choice":
        target = [probs.get(k, 0.0) for k in crit]
    elif t == "noul":
        target = [probs.get("false", 0.5), probs.get("true", 0.5)]
    else:
        target = [probs.get(str(i), 0.0) for i in range(len(crit))]
    s = sum(target)
    target = [v / s for v in target] if s > 0 else [1 / len(target)] * len(target)
    seq, markers = build_sequence(tok, state, {"t": t, "ins": q["instructions"], "crit": crit}, MAX_LEN, HEAD_MAX_LEN)
    if len(markers) != len(render_options({"t": t, "crit": crit})):
        return None
    return {"ids": seq, "markers": markers, "qtype": QTYPES[t], "target": target, "label": target.index(max(target))}


def collate(items, pad_id):
    n, length = len(items), max(len(it["ids"]) for it in items)
    kmax = max(len(it["markers"]) for it in items)
    ids = torch.full((n, length), pad_id, dtype=torch.long)
    att = torch.zeros((n, length), dtype=torch.long)
    mpos = torch.zeros((n, kmax), dtype=torch.long)
    mmask = torch.zeros((n, kmax), dtype=torch.bool)
    target = torch.zeros((n, kmax))
    for i, it in enumerate(items):
        ids[i, :len(it["ids"])] = torch.tensor(it["ids"])
        att[i, :len(it["ids"])] = 1
        k = len(it["markers"])
        mpos[i, :k] = torch.tensor(it["markers"])
        mmask[i, :k] = True
        target[i, :len(it["target"])] = torch.tensor(it["target"])
    return ids, att, mpos, mmask, target, torch.tensor([it["qtype"] for it in items])


def fit_temperature(pairs):
    if len(pairs) < 10:
        return 1.0
    kmax = max(len(z) for z, _ in pairs)
    zs = torch.full((len(pairs), kmax), -1e4)
    ts = torch.zeros((len(pairs), kmax))
    for i, (z, t) in enumerate(pairs):
        zs[i, :len(z)] = torch.tensor(z)
        ts[i, :len(t)] = torch.tensor(t)
    log_t = torch.zeros(1, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=100)

    def closure():
        opt.zero_grad()
        loss = -(ts * torch.log_softmax(zs / log_t.exp(), -1)).sum(-1).mean()
        loss.backward()
        return loss
    opt.step(closure)
    return float(torch.clamp(log_t.exp(), 0.1, 10.0).item())


def main() -> None:
    torch.set_num_threads(int(os.environ.get("THREADS", os.cpu_count() or 4)))
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else DATA_DIR / "laya-mapay")
    model_dir = Path(snapshot_download(BASE_REPO, allow_patterns=[f"{BASE_SUBFOLDER}/*"])) / BASE_SUBFOLDER
    _fix_tokenizer_config(str(model_dir))
    tok = AutoTokenizer.from_pretrained(model_dir / "tokenizer")
    cfg = json.loads((model_dir / "rl_agent_config.json").read_text())

    items = []
    for line in (DATA_DIR / "train.jsonl").read_text().splitlines():
        row = json.loads(line)
        state, questions, gold = json.loads(row["state"]), json.loads(row["questions"]), json.loads(row["gold"])
        items += [it for qid, q in questions.items() if qid in gold
                  and (it := training_item(tok, cfg, state, q, gold[qid]))]
    order = list(range(len(items)))
    random.Random(20260922).shuffle(order)
    n_calib = min(400, len(items) // 10)
    calib = [items[i] for i in sorted(order[:n_calib])]
    train = [items[i] for i in sorted(order[n_calib:])]

    model = build_model(cfg, encoder_dir=str(model_dir / "encoder"))
    model.load_state_dict(load_file(model_dir / "model.safetensors"), strict=True)
    model.train()
    enc = [p for n, p in model.named_parameters() if "encoder." in n]
    head = [p for n, p in model.named_parameters() if "encoder." not in n]
    optimizer = torch.optim.AdamW([{"params": enc, "lr": LR_ENCODER}, {"params": head, "lr": LR_HEAD}],
                                  weight_decay=0.01)
    total = max(1, (len(train) // (MICRO_BATCH * GRAD_ACCUM)) * EPOCHS)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=total, eta_min=1e-6)
    print(f"{len(train)} training sequences, {len(calib)} held out for calibration, {EPOCHS} epochs", flush=True)
    t0 = time.time()
    for epoch in range(EPOCHS):
        random.Random(42 + epoch).shuffle(train)
        sigma = SIGMA_START + (SIGMA_END - SIGMA_START) * epoch / max(1, EPOCHS - 1)
        optimizer.zero_grad(set_to_none=True)
        running, steps = 0.0, 0
        for start in range(0, len(train), MICRO_BATCH):
            ids, att, mpos, mmask, target, qtype = collate(train[start:start + MICRO_BATCH], tok.pad_token_id)
            logits, act = model(ids, att, mpos, mmask, qtype)
            k = mmask.sum(-1, keepdim=True).float()
            eps = torch.randn((GROUP_SIZE,) + logits.shape) * sigma * mmask
            eps = (eps - eps.sum(-1, keepdim=True) / k) * mmask
            z = logits.detach().unsqueeze(0) + eps
            q = torch.softmax(z.masked_fill(~mmask, -1e4), -1)
            with torch.no_grad():
                reward = proper_reward(q, target.unsqueeze(0), qtype, mmask, w_sph=0.75, w_rps=1.0)
                adv = (reward - reward.mean(0, keepdim=True)) / (reward.std() + 1e-6)
            logp = -(((z - logits.unsqueeze(0)) ** 2) * mmask).sum(-1) / (2 * sigma ** 2)
            loss_ce = -(target * torch.log_softmax(logits.masked_fill(~mmask, -1e4), -1)).sum(-1).mean()
            loss = (-(adv * logp).mean() + loss_ce) / GRAD_ACCUM + 0.0 * act.sum()
            loss.backward()
            steps += 1
            running += loss.item() * GRAD_ACCUM
            if steps % GRAD_ACCUM == 0 or start + MICRO_BATCH >= len(train):
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
            if steps % 25 == 0:
                print(f"  epoch {epoch + 1}/{EPOCHS} step {steps} loss {running / steps:.4f} "
                      f"({time.time() - t0:.0f}s)", flush=True)
        print(f"=== epoch {epoch + 1}/{EPOCHS}: loss {running / max(1, steps):.4f}, {time.time() - t0:.0f}s", flush=True)

    model.eval()
    preds = []
    with torch.no_grad():
        for start in range(0, len(calib), 16):
            chunk = calib[start:start + 16]
            ids, att, mpos, mmask, _, qtype = collate(chunk, tok.pad_token_id)
            logits, _ = model(ids, att, mpos, mmask, qtype)
            for row, it in enumerate(chunk):
                preds.append((it["qtype"], logits[row, :len(it["markers"])].tolist(), it["target"]))
    temps = [fit_temperature([(z, t) for qt, z, t in preds if qt == i]) for i in range(3)]
    print("calibration temperatures (choice, score, noul):", [round(t, 3) for t in temps], flush=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    save_file({k: v.half().contiguous() for k, v in model.state_dict().items()}, output_dir / "model.safetensors")
    model.encoder.config.save_pretrained(output_dir / "encoder")
    tok.save_pretrained(output_dir / "tokenizer")
    cfg.update({"fine_tuned": True, "model_name": "laya-mapay-news", "temperature": temps})
    cfg.pop("temperature_by_options", None)
    (output_dir / "rl_agent_config.json").write_text(json.dumps(cfg, indent=2))
    print(f"saved {output_dir}", flush=True)


if __name__ == "__main__":
    main()
