import time
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from tools.logger import get_logger, request_id_ctx, trace_id_ctx, user_id_ctx, session_id_ctx

logger = get_logger("middleware")

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()

        # 1. Extract or Generate IDs
        # Trace ID: Shared across services. Frontend should send it, or we generate one.
        trace_id = request.headers.get("X-Trace-ID") or str(uuid.uuid4())
        
        # Request ID: Unique for this service request.
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        
        # Session ID: Optional, from headers or auth (will be updated later if needed)
        session_id = request.headers.get("X-Session-ID")

        # 2. Set Context Variables
        trace_id_token = trace_id_ctx.set(trace_id)
        request_id_token = request_id_ctx.set(request_id)
        session_id_token = session_id_ctx.set(session_id)
        
        # Reset user_id at start of request (will be populated by Auth middleware)
        user_id_token = user_id_ctx.set(None)

        try:
            # 3. Log Request Start
            logger.info(f"Incoming request: {request.method} {request.url.path}")

            # 4. Process Request
            response = await call_next(request)

            # 5. Log Request Complete
            process_time = time.time() - start_time
            logger.info(
                f"Request completed",
                extra={"status_code": response.status_code}
            )
            
            # 6. Add IDs to Response Headers
            response.headers["X-Trace-ID"] = trace_id
            response.headers["X-Request-ID"] = request_id
            
            return response

        except Exception as e:
            logger.error(f"Request failed: {str(e)}", exc_info=True)
            raise e
        
        finally:
            # 7. Cleanup Context Variables
            trace_id_ctx.reset(trace_id_token)
            request_id_ctx.reset(request_id_token)
            session_id_ctx.reset(session_id_token)
            user_id_ctx.reset(user_id_token)
