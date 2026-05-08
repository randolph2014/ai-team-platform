import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="errorPanel" style={{ margin: 32 }}>
          <h2>页面出错</h2>
          <p>{this.state.error.message}</p>
          <button
            className="button primary"
            onClick={() => {
              this.setState({ error: null });
              window.location.href = '/';
            }}
          >
            刷新
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
