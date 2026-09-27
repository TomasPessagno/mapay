import { Component, type ErrorInfo, type ReactNode } from 'react';

// One malformed map feature used to take the whole app down (an uncaught render error unmounts the
// React root, leaving a grey screen). Contain it per tab: the rest of the app stays navigable and
// the user can reload.
interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Map tab crashed', error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <div
        role="alert"
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--system-background)',
          padding: '16px',
        }}
      >
        <div
          className="glass"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            padding: '8px 16px',
            borderRadius: '22px',
            boxShadow: '0 2px 10px rgba(0, 0, 0, 0.18)',
            color: 'var(--label)',
            fontSize: '15px',
            lineHeight: '20px',
            fontWeight: 500,
          }}
        >
          <span>Something went wrong</span>
          <span aria-hidden="true">·</span>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              all: 'unset',
              cursor: 'pointer',
              color: 'var(--ion-color-primary)',
              fontWeight: 600,
            }}
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
