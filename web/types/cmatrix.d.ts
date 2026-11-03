declare module "cmatrix" {
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
    mount?: (matrix: CMatrixInstance) => void;
    unmount?: (matrix: CMatrixInstance) => void;
    font?: string;
  }

  export interface CMatrix {
    (canvas: HTMLCanvasElement, options?: CMatrixOptions): Promise<void> | undefined;
    range(start: number, end: number): string[];
    custom_chars: string[];
  }

  const matrix: CMatrix;
  export default matrix;
}
