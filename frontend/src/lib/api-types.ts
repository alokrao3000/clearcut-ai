import type { Layer } from "@/lib/types";

export interface AddLayerBody {
  layer: Layer;
}

/** FastAPI's `detail` for the disclaimer gate and other coded errors. */
export interface CodedError {
  code?: string;
  message?: string;
  version?: string;
}

/** One entry of a Pydantic validation-error array. */
export interface ValidationError {
  msg?: string;
  loc?: unknown[];
}

/** `detail` is a string, a coded object, or a validation-error array. */
export type ApiErrorShape = CodedError | ValidationError[];

export function isCodedError(detail: unknown): detail is CodedError {
  return typeof detail === "object" && detail !== null && !Array.isArray(detail);
}
