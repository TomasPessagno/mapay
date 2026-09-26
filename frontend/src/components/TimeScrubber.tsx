interface Props {
  value: Date;
  onChange: (d: Date) => void;
}

export default function TimeScrubber({ value }: Props) {
  // TODO: Now / +30m / +1h / Custom
  return <div className="time-scrubber">{value.toLocaleTimeString()}</div>;
}
