import logging
import os
import json
import uuid
from tools.logger import get_logger, request_id_ctx

def verify_file_logging():
    log_file = "logs/app.log"
    
    # 1. Clean existing log file to ensure we verify just this run
    if os.path.exists(log_file):
        os.remove(log_file)
        print(f"Removed existing log file: {log_file}")

    # 2. Setup Logger
    logger = get_logger("file_verify_logger")
    
    # Set context
    test_id = str(uuid.uuid4())
    request_id_ctx.set(test_id)

    # 3. Log a message
    message = f"File logging test message {test_id}"
    logger.info(message)
    print(f"Logged message: {message}")

    # 4. Read file and verify
    if not os.path.exists(log_file):
        print("❌ FAILED: Log file was not created.")
        return

    with open(log_file, "r") as f:
        content = f.read()
    
    print(f"\n--- Log File Content ---\n{content}\n------------------------")

    try:
        # Loop through lines in case multiple logs were written (should be just one relevant one, but handling appendage)
        found = False
        for line in content.strip().split('\n'):
            if not line: continue
            log_json = json.loads(line)
            if log_json.get("request_id") == test_id and log_json.get("message") == message:
                found = True
                print("✅ SUCCESS: Log entry found in file and matches test data.")
                break
        
        if not found:
             print("❌ FAILED: Specific log entry not found in file.")

    except json.JSONDecodeError as e:
        print("❌ FAILED: File content is not valid JSON.")
        print(e)

if __name__ == "__main__":
    verify_file_logging()
