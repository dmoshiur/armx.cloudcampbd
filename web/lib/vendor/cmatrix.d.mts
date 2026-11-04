/** Type declarations for the vendored MIT cmatrix JavaScript port.
 * Source: jcubic/cmatrix 0.5.3 — see ./LICENSE
 */
export interface CMatrixInstance {
  start(): void;
  stop(): void;
  resize(width: number, height: number): void;
  clear(): void;
  reset(): void;
  fullscreen(): void;
  render(): void;
}

export interface CMatrixOptions {
  chars?: string[];
  exit?: boolean;
  color?: string;
  width?: number;
  height?: number;
  resize?: boolean;
  background?: string;
  font_size?: number;
  font?: string;
  mount?: (matrix: CMatrixInstance) => void;
  unmount?: (matrix: CMatrixInstance) => void;
}

export interface CMatrix {
  (canvas: HTMLCanvasElement, options?: CMatrixOptions): Promise<void> | undefined;
  range(start: number, end: number): string[];
  custom_chars: string[];
}

declare const matrix: CMatrix;
export default matrix;
