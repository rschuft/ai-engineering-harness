import { Component, type ErrorInfo, type ReactNode } from "react";
import { EmptyState } from "../areas/EmptyState";

interface State {
  error: Error | null;
}

/**
 * Contains a failure to load or render Agent Canvas to the engineering area,
 * and says so plainly instead of leaving a blank panel. The rest of the shell
 * keeps working.
 */
export class CanvasBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Agent Canvas failed to mount in the Owner host", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <EmptyState title="Agent Canvas could not be shown" testId="canvas-failed">
          <p>Agent Canvas failed to load inside the Owner host, so no engineering view is available.</p>
          <p>
            Reason: <code>{this.state.error.message}</code>
          </p>
        </EmptyState>
      );
    }
    return this.props.children;
  }
}
