import logging
import io
import json
import uuid
import sys
from tools.logger import get_logger, request_id_ctx, trace_id_ctx, user_id_ctx

def verify_log_format():
    # Capture stdout
    capture = io.StringIO()
    handler = logging.StreamHandler(capture)
    handler.setFormatter(get_logger("test").handlers[0].formatter)
    
    logger = get_logger("verify_logger")
    # Remove existing handlers to avoid double printing to console during test if any
    logger.handlers = [] 
    logger.addHandler(handler)
    
    # Set context
    r_id = str(uuid.uuid4())
    t_id = str(uuid.uuid4())
    u_id = "user-123"
    
    request_id_ctx.set(r_id)
    trace_id_ctx.set(t_id)
    user_id_ctx.set(u_id)
    
    # Log something
    logger.info("Test log message")
    
    # Get output
    output = capture.getvalue()
    print("Raw Output:", output)
    
    try:
        log_json = json.loads(output)
    except json.JSONDecodeError as e:
        print("❌ FAILED: Output is not valid JSON")
        print(e)
        return

    # Check fields
    required_fields = [
        "timestamp", "service", "layer", "module", "function", 
        "log_level", "message", "request_id", "trace_id", "user_id"
    ]
    
    missing = [f for f in required_fields if f not in log_json]
    
    if missing:
        print(f"❌ FAILED: Missing fields: {missing}")
    else:
        print("✅ SUCCESS: All required fields present.")
        print("Request ID match:", log_json["request_id"] == r_id)
        print("Trace ID match:", log_json["trace_id"] == t_id)
        print("User ID match:", log_json["user_id"] == u_id)

if __name__ == "__main__":
    verify_log_format()
