"""
Input validation module for API security and data integrity.
Implements comprehensive validation for all API endpoints.
"""

import re
import ast
import logging
from typing import List, Dict, Any, Optional, Union
from pydantic import BaseModel, validator, Field, ValidationError
from datetime import datetime

# Configure logging
logger = logging.getLogger(__name__)

# Security constants
MAX_PROMPT_LENGTH = 2000
MAX_CODE_LENGTH = 50000
MAX_TICKERS = 10
MIN_START_DATE = "2000-01-01"
MAX_END_DATE = "2026-12-31"
ALLOWED_TICKER_PATTERN = re.compile(r'^[A-Z]{1,5}(\.[A-Z]{1,3})?$')
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')

# Dangerous patterns to prevent in generated code
DANGEROUS_PATTERNS = [
    r'import\s+os',
    r'import\s+sys',
    r'import\s+subprocess',
    r'import\s+requests',
    r'import\s+urllib',
    r'from\s+os',
    r'from\s+sys',
    r'eval\s*\(',
    r'exec\s*\(',
    r'open\s*\(',
    r'file\s*\(',
    r'__import__',
    r'globals\s*\(',
    r'locals\s*\(',
    r'dir\s*\(',
    r'vars\s*\(',
    r'help\s*\(',
]

# Required patterns for valid VectorBT strategy code
REQUIRED_PATTERNS = [
    r'import\s+vectorbt\s+as\s+vbt',
]


class BaseValidationError(Exception):
    """Base exception for validation errors"""
    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


class SecurityValidationError(BaseValidationError):
    """Raised when security validation fails"""
    pass


class DataValidationError(BaseValidationError):
    """Raised when data validation fails"""
    pass


class StrategyValidator:
    """Validates trading strategy code for security and correctness"""

    @staticmethod
    def validate_code_length(code: str) -> None:
        """Validate code length to prevent abuse"""
        if not code or len(code.strip()) < 10:
            raise DataValidationError("Code too short or empty")

        if len(code) > MAX_CODE_LENGTH:
            raise DataValidationError(
                f"Code too long ({len(code)} chars). Maximum allowed: {MAX_CODE_LENGTH}"
            )

    @staticmethod
    def validate_dangerous_patterns(code: str) -> None:
        """Check for dangerous patterns in code"""
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                raise SecurityValidationError(
                    f"Dangerous pattern detected: {pattern}. "
                    f"Code execution aborted for security reasons."
                )

    @staticmethod
    def validate_required_patterns(code: str) -> None:
        """Check for required VectorBT patterns"""
        # Check if code imports vectorbt
        if not any('vectorbt' in line for line in code.split('\n')):
            raise DataValidationError(
                "Code must import vectorbt library."
            )

    @staticmethod
    def validate_ast_syntax(code: str) -> None:
        """Validate Python syntax using AST"""
        try:
            ast.parse(code)
        except SyntaxError as e:
            raise DataValidationError(f"Invalid Python syntax: {str(e)}")

    @staticmethod
    def validate_vectorbt_api(code: str) -> None:
        """Validate VectorBT API usage"""
        # Check for common VectorBT method calls
        vectorbt_methods = [
            'vbt.',
            'vectorbt.',
        ]

        found_methods = []
        for method in vectorbt_methods:
            if method in code:
                found_methods.append(method)

        if not found_methods:
            raise DataValidationError(
                "No VectorBT methods found. Code must use VectorBT library methods."
            )

    @staticmethod
    def detect_vbt_comparison_issues(code: str) -> List[str]:
        """Detect potential VectorBT comparison operator issues"""
        warnings = []

        # Check for patterns that use direct comparison operators with VBT indicators
        # These patterns work for single backtest but fail during optimization

        # Pattern: indicator.ma > other (for MA comparisons)
        if re.search(r'\.ma\s*>', code) or re.search(r'\.ma\s*<', code):
            warnings.append(
                "Detected direct comparison operators with MA. "
                "Consider using ma_above(), ma_below(), ma_crossed_above(), ma_crossed_below() "
                "for optimization compatibility."
            )

        # Pattern: indicator.rsi > value (for RSI comparisons)
        if re.search(r'\.rsi\s*>', code) or re.search(r'\.rsi\s*<', code):
            warnings.append(
                "Detected direct comparison operators with RSI. "
                "Consider using rsi_above(), rsi_below(), rsi_crossed_above(), rsi_crossed_below() "
                "for optimization compatibility."
            )

        # Pattern: using & or | for combining conditions
        if re.search(r'\)\s*&\s*\(', code) or re.search(r'\)\s*\|\s*\(', code):
            warnings.append(
                "Detected & or | operators for combining conditions. "
                "Consider using vbt.And(), vbt.Or(), vbt.Not() for optimization compatibility."
            )

        return warnings

    @classmethod
    def validate_strategy_code(cls, code: str) -> Dict[str, Any]:
        """Comprehensive strategy code validation"""
        validation_result: Dict[str, Any] = {
            "valid": True,
            "warnings": [],
            "errors": [],
            "suggestions": []
        }

        try:
            # Length validation
            cls.validate_code_length(code)

            # Security validation
            cls.validate_dangerous_patterns(code)

            # Syntax validation
            cls.validate_ast_syntax(code)

            # Required entry points (4-function template). Missing build_config
            # or a required function fails every run at import/execution.
            if 'def build_config' not in code and 'CONFIG' not in code:
                validation_result["errors"].append(
                    "Missing build_config() function or CONFIG attribute — the engine requires it."
                )
            _required = ['def precompute', 'def entry_score', 'def holding_score', 'def exit_check']
            _missing = [f for f in _required if f not in code]
            if _missing:
                validation_result["errors"].append(
                    "Missing required function(s): " + ", ".join(_missing)
                )

            # VectorBT API validation
            cls.validate_vectorbt_api(code)

            # Check for VBT comparison issues
            vbt_warnings = cls.detect_vbt_comparison_issues(code)
            validation_result["warnings"].extend(vbt_warnings)

            # Additional suggestions
            if 'print(' not in code:
                validation_result["suggestions"].append(
                    "Consider adding print(pf.stats()) for debugging"
                )

            if 'param' in code.lower() and '# Parameters' not in code:
                validation_result["suggestions"].append(
                    "Consider adding a '# Parameters' section for optimization"
                )

            # Suggest VBT comparison methods if indicators are used
            if any(ind in code for ind in ['vbt.MA.run', 'vbt.RSI.run', 'vbt.MACD.run']):
                if not any(method in code for method in ['ma_above', 'ma_below', 'rsi_above', 'rsi_below']):
                    validation_result["suggestions"].append(
                        "For optimization compatibility, use VBT comparison methods "
                        "(e.g., ma_above(), rsi_below()) instead of direct operators (>, <)"
                    )

        except SecurityValidationError as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Security: {e.message}")
        except DataValidationError as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Data: {e.message}")
        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Validation error: {str(e)}")

        logger.info("Strategy validation completed. Valid: %s", validation_result['valid'])
        return validation_result


class ParameterValidator:
    """Validates optimization parameters"""

    @staticmethod
    def validate_param_ranges(params: Dict[str, Any]) -> None:
        """Validate parameter optimization ranges"""
        for name, value in params.items():
            if isinstance(value, dict):
                # Range format: {"start": x, "stop": y, "step": z}
                if not all(key in value for key in ["start", "stop", "step"]):
                    raise DataValidationError(
                        f"Parameter '{name}' missing required keys: start, stop, step"
                    )

                start, stop, step = value["start"], value["stop"], value["step"]

                # Validate numeric values
                for key, val in [("start", start), ("stop", stop), ("step", step)]:
                    if not isinstance(val, (int, float)):
                        raise DataValidationError(
                            f"Parameter '{name}' {key} must be numeric, got {type(val)}"
                        )

                # Validate range logic
                if start >= stop:
                    raise DataValidationError(
                        f"Parameter '{name}': start ({start}) must be < stop ({stop})"
                    )

                if step <= 0:
                    raise DataValidationError(
                        f"Parameter '{name}': step ({step}) must be positive"
                    )

                # Limit number of combinations
                num_values = int((stop - start) / step) + 1
                if num_values > 1000:
                    raise DataValidationError(
                        f"Parameter '{name}': too many combinations ({num_values}). "
                        f"Maximum allowed: 1000"
                    )

    @staticmethod
    def validate_param_names(params: Dict[str, Any]) -> None:
        """Validate parameter names"""
        for name in params.keys():
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
                raise DataValidationError(
                    f"Invalid parameter name '{name}'. Must match: ^[a-zA-Z_][a-zA-Z0-9_]*$"
                )


class DataValidator:
    """Validates market data parameters"""

    @staticmethod
    def validate_tickers(tickers: List[str]) -> None:
        """Validate ticker symbols"""
        if not tickers:
            raise DataValidationError("At least one ticker must be provided")

        if len(tickers) > MAX_TICKERS:
            raise DataValidationError(
                f"Too many tickers ({len(tickers)}). Maximum allowed: {MAX_TICKERS}"
            )

        for ticker in tickers:
            # Strict validation: Uppercase only as per pattern
            if not ALLOWED_TICKER_PATTERN.match(ticker):
                raise DataValidationError(
                    f"Invalid ticker symbol '{ticker}'. "
                    f"Must match pattern: ^[A-Z]{{1,5}}(\\.[A-Z]{{1,3}})?$"
                )

    @staticmethod
    def validate_date_range(start_date: str, end_date: str) -> None:
        """Validate date parameters"""
        # Strict format check
        if not DATE_PATTERN.match(start_date) or not DATE_PATTERN.match(end_date):
            raise DataValidationError("Invalid date format. Use YYYY-MM-DD")

        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            min_date = datetime.strptime(MIN_START_DATE, "%Y-%m-%d")
            max_date = datetime.strptime(MAX_END_DATE, "%Y-%m-%d")
        except ValueError as e:
            raise DataValidationError(f"Invalid date format. Use YYYY-MM-DD: {str(e)}")

        if start < min_date:
            raise DataValidationError(f"Start date too early. Minimum: {MIN_START_DATE}")

        if end > max_date:
            raise DataValidationError(f"End date too late. Maximum: {MAX_END_DATE}")

        if start >= end:
            raise DataValidationError("Start date must be before end date")

        # Check date range is reasonable
        if (end - start).days < 30:
            raise DataValidationError("Date range too short. Minimum: 30 days")


class PromptValidator:
    """Validates strategy generation prompts"""

    @staticmethod
    def validate_prompt_length(prompt: str) -> None:
        """Validate prompt length"""
        if len(prompt.strip()) < 10:
            raise DataValidationError("Prompt too short. Minimum: 10 characters")

        if len(prompt) > MAX_PROMPT_LENGTH:
            raise DataValidationError(
                f"Prompt too long ({len(prompt)} chars). Maximum: {MAX_PROMPT_LENGTH}"
            )

    @staticmethod
    def validate_prompt_content(prompt: str) -> None:
        """Validate prompt content for inappropriate content"""
        # Check for obviously inappropriate content
        inappropriate_keywords = [
            'pump and dump',
            'insider trading',
            'market manipulation',
            'illegal'
        ]

        prompt_lower = prompt.lower()
        for keyword in inappropriate_keywords:
            if keyword in prompt_lower:
                raise DataValidationError(
                    f"Inappropriate content detected: '{keyword}'. "
                    f"Please use appropriate trading strategy descriptions."
                )


# Pydantic models for API validation

class GenerateRequest(BaseModel):
    """Validated request model for strategy generation"""
    prompt: str = Field(..., min_length=10, max_length=MAX_PROMPT_LENGTH)
    tickers: List[str] = Field(..., min_length=1, max_length=MAX_TICKERS)
    start_date: str = Field(..., pattern=r'^\d{4}-\d{2}-\d{2}$')
    end_date: str = Field(..., pattern=r'^\d{4}-\d{2}-\d{2}$')

    @validator('tickers')
    def validate_tickers(cls, v):
        DataValidator.validate_tickers(v)
        return v

    @validator('start_date', 'end_date')
    def validate_dates(cls, v, values, **kwargs):
        if 'start_date' in values and 'end_date' in values:
            DataValidator.validate_date_range(values['start_date'], v)
        return v

    @validator('prompt')
    def validate_prompt(cls, v):
        PromptValidator.validate_prompt_length(v)
        PromptValidator.validate_prompt_content(v)
        return v


class RunRequest(BaseModel):
    """Validated request model for strategy execution"""
    code: str = Field(..., min_length=50, max_length=MAX_CODE_LENGTH)

    @validator('code')
    def validate_code(cls, v):
        StrategyValidator.validate_strategy_code(v)
        return v


class OptimizeRequest(BaseModel):
    """Validated request model for parameter optimization"""
    code: str = Field(..., min_length=50, max_length=MAX_CODE_LENGTH)
    strategy_params: Dict[str, Any] = Field(..., min_length=0, max_length=10)
    config: Dict[str, Any] = Field(..., min_length=1)

    @validator('code')
    def validate_code(cls, v):
        StrategyValidator.validate_strategy_code(v)
        return v

    @validator('strategy_params')
    def validate_strategy_params(cls, v):
        ParameterValidator.validate_param_names(v)
        ParameterValidator.validate_param_ranges(v)
        return v

    @validator('config')
    def validate_config(cls, v):
        valid_modes = ['simple', 'wfo', 'true_wfo']
        valid_metrics = ['total_return', 'sharpe', 'sortino', 'max_dd']

        if v.get('mode') not in valid_modes:
            raise DataValidationError(f"Invalid mode. Valid options: {valid_modes}")

        if v.get('metric') not in valid_metrics:
            raise DataValidationError(f"Invalid metric. Valid options: {valid_metrics}")

        return v


class TrueWFORequest(BaseModel):
    """Validated request model for True Walk-Forward Optimization"""
    code: str = Field(..., min_length=50, max_length=MAX_CODE_LENGTH)
    strategy_params: Dict[str, Any] = Field(..., min_length=0, max_length=10)
    config: Dict[str, Any] = Field(..., min_length=1)

    @validator('code')
    def validate_code(cls, v):
        StrategyValidator.validate_strategy_code(v)
        return v

    @validator('strategy_params')
    def validate_strategy_params(cls, v):
        if len(v) > 0:
            ParameterValidator.validate_param_names(v)
            ParameterValidator.validate_param_ranges(v)
        return v

    @validator('config')
    def validate_config(cls, v):
        valid_modes = ['simple', 'wfo', 'true_wfo']
        valid_metrics = ['total_return', 'sharpe', 'sortino', 'max_dd']

        if v.get('mode') not in valid_modes:
            raise DataValidationError(f"Invalid mode. Valid options: {valid_modes}")

        if v.get('metric') not in valid_metrics:
            raise DataValidationError(f"Invalid metric. Valid options: {valid_metrics}")

        return v


class StrategyName(BaseModel):
    """Validated strategy name for save/load operations"""
    name: str = Field(..., min_length=1, max_length=50, pattern=r'^[a-zA-Z0-9_\-\.]+$')


def validate_api_request(request_type: str, data: Dict[str, Any]) -> Any:
    """
    Main validation function for API requests

    Args:
        request_type: Type of request ('generate', 'run', 'optimize', 'true-wfo')
        data: Request data dictionary

    Returns:
        Validated request object

    Raises:
        BaseValidationError: If validation fails
    """
    try:
        if request_type == 'generate':
            return GenerateRequest(**data)
        elif request_type == 'run':
            return RunRequest(**data)
        elif request_type == 'optimize':
            return OptimizeRequest(**data)
        elif request_type == 'true-wfo':
            return TrueWFORequest(**data)
        else:
            raise DataValidationError(f"Unknown request type: {request_type}")

    except ValidationError as e:
        logger.warning(f"Pydantic validation error: {e}")
        error_msgs = []
        for err in e.errors():
            loc = ".".join(str(l) for l in err.get('loc', []))
            msg = err.get('msg', '')
            error_msgs.append(f"{loc}: {msg}")
        raise DataValidationError(f"Invalid request data: {'; '.join(error_msgs)}")
    except Exception as e:
        logger.error(f"Validation error for {request_type}: {str(e)}")
        if isinstance(e, BaseValidationError):
            raise
        raise DataValidationError(f"Validation failed: {str(e)}")


# Utility functions for common validations

def sanitize_filename(filename: str) -> str:
    """Sanitize filename for safe file operations"""
    # Remove dangerous characters
    filename = re.sub(r'[^\w\-_.]', '_', filename)

    # Limit length
    if len(filename) > 50:
        filename = filename[:50]

    # Ensure it ends with .py
    if not filename.endswith('.py'):
        filename += '.py'

    return filename


def validate_file_path(path: str, base_dir: str) -> bool:
    """Validate file path to prevent directory traversal"""
    import os.path

    # Normalize the path
    normalized_path = os.path.normpath(path)

    # Check if path is within base directory
    full_path = os.path.join(base_dir, normalized_path)
    resolved_base = os.path.realpath(base_dir)
    resolved_path = os.path.realpath(full_path)

    return resolved_path.startswith(resolved_base)
