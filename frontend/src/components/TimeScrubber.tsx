import { useState } from 'react';
import { IonButton, IonDatetime, IonLabel, IonSegment, IonSegmentButton } from '@ionic/react';

interface Props {
  value: Date | null;
  onChange: (departure: Date | null) => void;
}

function nextQuarterHour(from: Date): Date {
  const next = new Date(from);
  next.setSeconds(0, 0);
  next.setMinutes(Math.ceil((next.getMinutes() + 1) / 15) * 15);
  return next;
}

export default function TimeScrubber({ value, onChange }: Props) {
  const [pickerOpen, setPickerOpen] = useState(false);
  const now = new Date();
  const max = new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000);

  const chooseMode = (mode: string) => {
    if (mode === 'now') {
      setPickerOpen(false);
      onChange(null);
      return;
    }
    if (!value) onChange(nextQuarterHour(now));
    setPickerOpen(true);
  };

  return (
    <div className="departure-time-control">
      <IonSegment
        mode="ios"
        value={value ? 'scheduled' : 'now'}
        onIonChange={(event) => chooseMode(String(event.detail.value ?? 'now'))}
        aria-label="When to leave"
      >
        <IonSegmentButton value="now" aria-label="Leave now">
          <IonLabel>Leave now</IonLabel>
        </IonSegmentButton>
        <IonSegmentButton value="scheduled" aria-label="Leave at a set time">
          <IonLabel>Leave at…</IonLabel>
        </IonSegmentButton>
      </IonSegment>

      {value && (
        <div className="departure-picker">
          <div className="departure-picker-heading">
            <IonLabel>Choose date and time</IonLabel>
            <IonButton
              fill="clear"
              size="small"
              onClick={() => setPickerOpen((open) => !open)}
              aria-label={pickerOpen ? 'Done choosing departure time' : 'Change departure time'}
            >
              {pickerOpen ? 'Done' : 'Change'}
            </IonButton>
          </div>
          {pickerOpen && (
            <IonDatetime
              className="departure-datetime"
              presentation="date-time"
              preferWheel
              hourCycle="h12"
              value={value.toISOString()}
              min={now.toISOString()}
              max={max.toISOString()}
              onIonChange={(event) => {
                const raw = event.detail.value;
                if (typeof raw !== 'string') return;
                const next = new Date(raw);
                if (Number.isNaN(next.getTime())) return;
                const current = new Date();
                const latest = new Date(current.getTime() + 7 * 24 * 60 * 60 * 1000);
                if (next >= current && next <= latest) onChange(next);
              }}
              aria-label="Choose departure date and time"
            />
          )}
        </div>
      )}
    </div>
  );
}
