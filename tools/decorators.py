import functools
import inspect
from tools.logger import get_logger

logger = get_logger("decorator")

def log_function_call(func):
    """
    Decorator to log function entry, exit, and errors.
    Captures arguments and execution time.
    """
    @functools.wraps(func)
    async def async_wrapper(*function_arg, **kwfunction_arg):
        func_name = func.__name__
        module_name = func.__module__
        
        # Sanitize sensitive function_arg if necessary (simplistic view for now)
        # Avoid logging 'password', 'token', etc.
        safe_kwfunction_arg = {k: v for k, v in kwfunction_arg.items() if 'password' not in k.lower() and 'token' not in k.lower()}
        
        logger.info(f"Calling function: {func_name}", extra={"function_arg": safe_kwfunction_arg})
        
        try:
            result = await func(*function_arg, **kwfunction_arg)
            logger.info(f"Function {func_name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Function {func_name} failed: {str(e)}", exc_info=True)
            raise e

    @functools.wraps(func)
    def sync_wrapper(*function_arg, **kwfunction_arg):
        func_name = func.__name__
        # module_name = func.__module__
        
        safe_kwfunction_arg = {k: v for k, v in kwfunction_arg.items() if 'password' not in k.lower() and 'token' not in k.lower()}
        
        logger.info(f"Calling function: {func_name}", extra={"function_arg": safe_kwfunction_arg})
        
        try:
            result = func(*function_arg, **kwfunction_arg)
            logger.info(f"Function {func_name} completed successfully")
            return result
        except Exception as e:
            logger.error(f"Function {func_name} failed: {str(e)}", exc_info=True)
            raise e

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
