import { useState } from 'react';
import { IonButton, IonDatetime, IonLabel, IonSegment, IonSegmentButton } from '@ionic/react';
import { formatClockTime, toLocalDatetimeValue } from '../lib/departureTime';

interface Props {
  value: Date | null;
  onChange: (departure: Date | null) => void;
  compact?: boolean;
  compactLabel?: string;
}

function nextQuarterHour(from: Date): Date {
  const next = new Date(from);
  next.setSeconds(0, 0);
  next.setMinutes(Math.ceil((next.getMinutes() + 1) / 15) * 15);
  return next;
}

export default function TimeScrubber({ value, onChange, compact = false, compactLabel }: Props) {
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

  const handleDateChange = (raw: string | string[] | null | undefined) => {
    if (typeof raw !== 'string') return;
    // IonDatetime emits local wall-time ISO without a zone; Date parses it in the device zone.
    // Explicit zone suffixes from native/browser adapters remain valid as well.
    const next = new Date(raw);
    if (Number.isNaN(next.getTime())) return;
    const current = new Date();
    const latest = new Date(current.getTime() + 7 * 24 * 60 * 60 * 1000);
    if (next >= current && next <= latest) onChange(next);
  };

  const datePicker = value && (
    <IonDatetime
      className="departure-datetime"
      presentation="date-time"
      preferWheel
      hourCycle="h12"
      value={toLocalDatetimeValue(value)}
      min={toLocalDatetimeValue(now)}
      max={toLocalDatetimeValue(max)}
      onIonChange={(event) => handleDateChange(event.detail.value)}
      aria-label="Choose departure date and time"
    />
  );

  if (compact) {
    return (
      <div className="departure-time-control departure-time-control-compact">
        <div className="departure-compact-row">
          <span className="departure-compact-label">
            {compactLabel ?? (value ? `Leave at ${formatClockTime(value)}` : 'Leave now')}
          </span>
          <IonButton
            fill="clear"
            size="small"
            onClick={() => setPickerOpen((open) => !open)}
            aria-label={pickerOpen ? 'Done changing departure time' : 'Change departure time'}
          >
            {pickerOpen ? 'Done' : 'Change'}
          </IonButton>
        </div>
        {pickerOpen && (
          <div className="departure-picker">
            <div className="departure-picker-heading">
              <IonLabel>Choose date and time</IonLabel>
              {value ? (
                <IonButton
                  fill="clear"
                  size="small"
                  onClick={() => {
                    setPickerOpen(false);
                    onChange(null);
                  }}
                  aria-label="Leave now"
                >
                  Leave now
                </IonButton>
              ) : (
                <IonButton fill="clear" size="small" onClick={() => onChange(nextQuarterHour(new Date()))}>
                  Leave at…
                </IonButton>
              )}
            </div>
            {datePicker}
          </div>
        )}
      </div>
    );
  }

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
          {pickerOpen && datePicker}
        </div>
      )}
    </div>
  );
}
