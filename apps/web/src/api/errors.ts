export class ApiHttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiHttpError";
  }
}

export class ApiInvalidJsonError extends Error {
  constructor(message = "The Diagnosis Service returned invalid JSON.") {
    super(message);
    this.name = "ApiInvalidJsonError";
  }
}

export class ApiInvalidResponseError extends Error {
  constructor(
    message = "The Diagnosis Service returned an unexpected response.",
  ) {
    super(message);
    this.name = "ApiInvalidResponseError";
  }
}

export class ApiConnectionError extends Error {
  constructor(message = "Unable to connect to the Diagnosis Service.") {
    super(message);
    this.name = "ApiConnectionError";
  }
}

export function safeErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "An unexpected error occurred.";
}
