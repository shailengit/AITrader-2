"""
LLM Engine Module - Local LLM integration for QuantGen strategy generation.
Generates and fixes vectorbt strategy code using locally hosted model (kimi-k2.5:cloud).
"""

import os
import re
import logging
from typing import List, Dict, Any, Optional

# Import lessons learned store for prompt enhancement
from app.services.lessons_learned import LessonsLearnedStore

# Configure logging
logger = logging.getLogger(__name__)

# Lazy-initialized lessons store
_lessons_store: Optional[LessonsLearnedStore] = None


def _get_lessons_store() -> LessonsLearnedStore:
    """Get or create the lessons learned store."""
    global _lessons_store
    if _lessons_store is None:
        _lessons_store = LessonsLearnedStore()
    return _lessons_store


def get_enhanced_system_prompt() -> str:
    """Build system prompt with dynamically injected lessons learned."""
    lessons_text = _get_lessons_store().get_formatted(n_recent=20)
    if lessons_text:
        return SYSTEM_PROMPT + "\n\n" + lessons_text
    return SYSTEM_PROMPT

# Try to import OpenAI SDK for local API compatibility
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not available. LLM features will be disabled.")

# Model configuration
# Try common Ollama model name formats
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "kimi-k2.6:cloud")
MAX_TOKENS = 4096  # Reduced for faster responses
REQUEST_TIMEOUT = 180  # seconds - maximum time to wait for LLM response (increased for complex strategy generation)

# Configuration for local model server (module level for accessibility)
LOCAL_API_BASE = os.environ.get("LOCAL_LLM_API_BASE", "http://localhost:11434/v1")
LOCAL_API_KEY = os.environ.get("LOCAL_LLM_API_KEY", "not-needed")

# Initialize client for local model server
client = None
if OPENAI_AVAILABLE:
    try:
        client = OpenAI(  # type: ignore[possibly-unbound]
            base_url=LOCAL_API_BASE,
            api_key=LOCAL_API_KEY,
            timeout=REQUEST_TIMEOUT,
            max_retries=1  # Reduce retries to avoid long waits on timeout (total wait = timeout * (retries + 1))
        )
        logger.info("Local LLM client initialized (endpoint: %s, timeout: %ds, max_retries=1)", LOCAL_API_BASE, REQUEST_TIMEOUT)
    except Exception as e:
        logger.error("Failed to initialize local LLM client: %s", e)

def verify_llm_connection() -> tuple[bool, Optional[str]]:
    """Quick check to verify LLM server is responsive."""
    if client is None:
        return False, "Client not initialized"

    import time
    try:
        start = time.time()
        # Send a minimal test request
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
            timeout=10,
        )
        elapsed = time.time() - start
        logger.info("LLM connection verified in %.2fs", elapsed)
        return True, None
    except Exception as e:
        return False, str(e)

SYSTEM_PROMPT = """You are an expert Quantitative Developer specializing in the `vectorbt` Python library.
Your goal is to write COMPLETE, STANDALONE, RUNNABLE Python scripts for trading strategies.

RULES:
1. **CRITICAL**: The script MUST start with a section exactly named `# Parameters` containing ALL tunable NUMERIC variables (integers/floats) assigned to simple values. DO NOT include strings, lists, or other types in this section.
   Example:
   ```python
   import vectorbt as vbt
   import pandas as pd
   import numpy as np

   # Parameters
   sma_window = 20
   rsi_period = 14
   rsi_threshold = 30.5

   # ... rest of imports and code ...
   ```
2. Use `vectorbt` as `vbt`.
3. **CRITICAL - USE LOCAL DATABASE**: Use the pre-imported DataService to fetch data from the local PostgreSQL database. DO NOT use vbt.YFData.download().
   ```python
   # DataService is already imported and available
   # Parameters
   ticker = 'AAPL'

   # ... later in the code ...
   data = DataService.get_ohlcv_data(ticker, start, end)
   ```
   NOTE: Do NOT include `from app.services.data_service import DataService` in your code - DataService is already available.
   NOTE: DataService will raise a clear ValueError if the ticker does not exist in the database or the date range is invalid. You do NOT need to manually check for None or empty data.
4. CRITICAL: Store the data result in a variable named `data` and DO NOT overwrite it.
5. Access price columns from `data` for calculations using bracket notation: `close = data['Close']`.
   ```python
   close = data['Close']
   open_price = data['Open']
   high = data['High']
   low = data['Low']
   volume = data['Volume']
   ```
6. When creating the Portfolio (e.g., `vbt.Portfolio.from_signals`), you MUST pass the Open/High/Low/Close data if available to enable realistic inspection.
   - Example: `vbt.Portfolio.from_signals(close, ..., open=data['Open'], high=data['High'], low=data['Low'])`
7. **CRITICAL - OPTIMIZATION COMPATIBILITY**: Strategy code MUST work for both single backtests AND multi-parameter optimization. This project uses **vectorbt 1.0.0**. The `.vbt.gt()/.lt()` accessor methods, `vbt.combine_logic()`, and the `jitted=True` kwarg DO NOT EXIST in this version — do NOT use them. Instead, use **plain pandas operators** (`>`, `<`, `&`, `|`) on operands that have been broadcast to the same shape.

   **A. Parameterized Indicators**
   Call every parameterized indicator with `.run()` and pass parameters as variables (VBT converts them to grids during optimization):
   ```python
   fast_ma = vbt.MA.run(close, window=fast_window).ma
   slow_ma = vbt.MA.run(close, window=slow_window).ma
   rsi = vbt.RSI.run(close, window=rsi_period).rsi
   ```

   **B. Broadcast operands to the same shape**
   During optimization, parameterized indicators become DataFrames with MultiIndex columns while non-parameterized operands stay Series. Comparing them directly raises "Operands are not aligned" / "Can only compare identically-labeled DataFrame objects". Define this helper and broadcast every non-parameterized operand against the parameterized one:
   ```python
   def _bc(s, ref):
       # Broadcast s to match ref's shape/columns for safe &/| with MultiIndex columns.
       if isinstance(s, pd.Series) and isinstance(ref, (pd.DataFrame, pd.Series)) and hasattr(ref, 'columns') and ref.columns.nlevels > 1:
           return pd.DataFrame(np.broadcast_to(s.values[:, None], ref.shape), index=ref.index, columns=ref.columns)
       if isinstance(s, pd.DataFrame) and isinstance(ref, pd.DataFrame):
           if s.columns.nlevels != ref.columns.nlevels or s.columns.tolist() != ref.columns.tolist():
               return pd.DataFrame(np.broadcast_to(s.values, ref.shape), index=ref.index, columns=ref.columns)
       return s
   ```

   **C. Use plain operators on broadcast operands**
   ```python
   ef_bc = fast_ma
   es_bc = _bc(slow_ma, fast_ma)
   close_bc = _bc(close, fast_ma)
   entries = (ef_bc > es_bc) & (close_bc > ef_bc)
   exits = ef_bc < es_bc
   ```

   **D. Portfolio**
   Always pass `broadcast_kwargs={'keep_pd': True}` to `vbt.Portfolio.from_signals`. Do NOT pass `jitted=True` (not a valid kwarg in vectorbt 1.0.0):
   ```python
   pf = vbt.Portfolio.from_signals(
       close,
       entries=entries,
       exits=exits,
       broadcast_kwargs={'keep_pd': True},
   )
   ```

8. **CRITICAL - CONTINUOUS SIGNALS FOR WALK-FORWARD**: For True Walk-Forward Optimization to work with short test windows, you MUST generate a signal EVERY DAY, not just on crossover events.

   EVENT-DRIVEN (WRONG for True WFO - only triggers on specific days):
   ```python
   entries = fast_ma.ma_crossed_above(slow_ma.ma)  # Only True ON the crossover day
   exits = fast_ma.ma_crossed_below(slow_ma.ma)  # Only True ON the crossunder day
   ```

   CONTINUOUS (CORRECT for True WFO - gives position every day):
   ```python
   # Method A: State-based (hold while condition is met)
   entries = fast_ma.ma_above(slow_ma.ma)  # True EVERY DAY fast > slow
   exits = fast_ma.ma_below(slow_ma.ma)    # True EVERY DAY fast < slow

   # Method B: Price-vs-level (use standard operators for price comparisons)
   entries = close > slow_ma.ma            # True EVERY DAY price > MA
   exits = close < slow_ma.ma              # True EVERY DAY price < MA

   # Method B2: Price-vs-level with VBT crossed methods (event-driven, NOT for True WFO)
   # Note: crossed_above/crossed_below are for event-driven signals only (trigger once)
   # entries = close.vbt.crossed_above(slow_ma.ma)  # Only True ON crossover day
   # exits = close.vbt.crossed_below(slow_ma.ma)    # Only True ON crossunder day

   # Method C: Momentum with threshold (directional bias)
   entries = rsi.rsi_below(50)             # True EVERY DAY RSI < 50 (oversold bounce)
   exits = rsi.rsi_above(50)               # True EVERY DAY RSI > 50
   ```

   **Why this matters**: `from_signals` holds a LONG position while `entries=True` and `exits=False`. With continuous signals, you get a position decision every single day. With event-driven signals, you might get no signal for days/weeks.

   **For True WFO**: Use state-based methods (`ma_above`, `ma_below`, `rsi_below`, etc.) NOT crossed methods (`ma_crossed_above`, etc.).

9. **CRITICAL - POSITION-AWARE SIGNAL LOGIC**: The generated strategy MUST explicitly track position state and only generate signals when position changes are needed.

   **Position Rules**:
   - **BUY**: Only when entry signal is True AND currently NOT in position (flat)
   - **SELL**: Only when exit signal is True AND currently IN position (long)
   - **HOLD**: When both entry and exit are False, OR when entry=True but already in position, OR when exit=True but already flat

   **WRONG** (generates signals regardless of position):
   ```python
   # This would try to buy every day while condition is true
   entries = fast_ma.ma_above(slow_ma.ma)
   exits = fast_ma.ma_below(slow_ma.ma)
   ```

   **CORRECT** (position-aware signals):
   ```python
   # Generate raw signals
   raw_long = fast_ma.ma_above(slow_ma.ma)   # Condition for being long
   raw_short = fast_ma.ma_below(slow_ma.ma)  # Condition for being flat/short

   # Create position-aware signals using diff() to detect changes
   # Only trigger when we transition from flat to long
   entries = raw_long & ~raw_long.shift(1).fillna(False)

   # Only trigger when we transition from long to flat
   exits = raw_short & ~raw_short.shift(1).fillna(False)

   # Alternative: Use vbt.Portfolio.from_signals with direction='longonly'
   # and continuous signals - VBT handles position internally
   pf = vbt.Portfolio.from_signals(
       close,
       entries=raw_long,      # Want to be long when this is True
       exits=raw_short,       # Want to exit when this is True
       direction='longonly',  # Only long positions, no shorting
       freq='1d'
   )
   ```

   **Key Point**: Use `direction='longonly'` in `from_signals()` combined with continuous raw signals. VBT will automatically:
   - Enter long when `entries` becomes True (and not already in position)
   - Exit long when `exits` becomes True (and currently in position)
   - Hold position when both are False
   - Never double-buy or sell without position

8. The script MUST run top-to-bottom without external dependencies other than standard libraries + pandas/numpy/vectorbt.
9. DO NOT use `input()`.
10. DO NOT omit imports.
11. At the end, print total return using `print(pf.total_return())`. NOTE: DO NOT use `pf.stats()` as it causes errors with multi-parameter optimization.
12. **CRITICAL**: Wrap ALL code in a markdown python code block like this:
    ```python
    # your code here
    ```
    Do NOT include any explanatory text outside the code block - only the runnable Python code.

**COMPLETE WORKING EXAMPLE using DataService (follow this pattern exactly):**
```python
import vectorbt as vbt
import pandas as pd
import numpy as np
from app.services.data_service import DataService

# Parameters
fast_window = 5
slow_window = 20
ticker = 'AAPL'
start = '{{START_DATE}}'
end = '{{END_DATE}}'

# Load data from local database
data = DataService.get_ohlcv_data(ticker, start, end)

# Get close price using bracket notation
close = data['Close']

# Calculate moving averages
fast_ma = vbt.MA.run(close, window=fast_window)
slow_ma = vbt.MA.run(close, window=slow_window).ma

# Broadcast non-parameterized operands to match fast_ma (see rule 7)
ef_bc = fast_ma
es_bc = _bc(slow_ma, fast_ma)

# Generate continuous signals for True WFO (plain operators on broadcast operands)
entries = ef_bc > es_bc
exits = ef_bc < es_bc

# Create portfolio with OHLC data
pf = vbt.Portfolio.from_signals(
    close,
    entries=entries,
    exits=exits,
    open=data['Open'],
    high=data['High'],
    low=data['Low'],
    direction='longonly',
    broadcast_kwargs={'keep_pd': True},
)

# Print total return
print(pf.total_return())
```

When fixing errors:
- Analyze the error message.
- Fix the specific line or logic causing it.
- Return the full corrected code.
- If the error mentions "cannot join with no overlapping index names", "Operands are not aligned", or "Can only compare identically-labeled", broadcast the operands to the same shape with the `_bc()` helper and use plain operators, as shown in rule 7.
"""

CHAT_SYSTEM_PROMPT = """You are an expert Python developer specializing in the `vectorbt` library for quantitative trading.
Your role is to answer questions about the provided code, explain concepts, and help debug issues.

Guidelines:
1. Be helpful, concise, and accurate
2. When providing code fixes, use markdown code blocks with python
3. Explain your reasoning
4. Focus on vectorbt, pandas, numpy, and trading strategy concepts
5. If asked to modify code, provide the full corrected version or the specific changes needed

The user is working with the following vectorbt strategy code:

IMPORTANT: When generating a strategy description prompt for the user, keep it under 2000 characters to ensure it fits well in the Strategy Description text area.
"""


def extract_code_block(text: str) -> Optional[str]:
    """
    Extracts python code from markdown code blocks.
    Falls back to raw text if no blocks found, with cleanup for common LLM output patterns.
    Returns None if a code block is found but empty, or no code pattern is found.
    """
    # First try to find python code blocks
    pattern = r"```python(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        extracted = matches[0].strip()
        # If the extracted code is empty, return None to signal failure
        if not extracted:
            return None
        return extracted

    # Fallback to generic code blocks
    pattern_generic = r"```(.*?)```"
    matches_generic = re.findall(pattern_generic, text, re.DOTALL)
    if matches_generic:
        extracted = matches_generic[0].strip()
        # If the extracted code is empty, return None to signal failure
        if not extracted:
            return None
        return extracted

    # No code blocks found - try to extract code by looking for Python markers
    # Look for common Python file starters
    code_starters = [
        r'(import\s+\w+)',  # import statement
        r'(from\s+\w+\s+import)',  # from import
        r'(#\s*Parameters)',  # Parameters comment
        r'(#\s*Strategy)',  # Strategy comment
    ]

    for starter_pattern in code_starters:
        match = re.search(starter_pattern, text, re.IGNORECASE)
        if match:
            # Extract from the start of the match to the end
            start_idx = match.start()
            return text[start_idx:].strip()

    # Last resort: try to remove common explanatory prefixes
    lines = text.split('\n')
    code_lines = []
    in_code = False

    for line in lines:
        stripped = line.strip()
        # Skip empty lines and common intro lines
        if not stripped:
            continue
        # Skip lines that are clearly not code
        if re.match(r'^(Here is|This is|Below is|I\'ve created|I have|Let me|Sure|Okay)', stripped, re.IGNORECASE):
            continue
        # Once we see import or def or #, start collecting code
        if re.match(r'^(import|from|def|class|#)', stripped):
            in_code = True
        if in_code:
            code_lines.append(line)

    if code_lines:
        return '\n'.join(code_lines).strip()

    # Final fallback: return cleaned text
    return text.strip()


def transform_code_for_local_data(code: str) -> str:
    """
    Transform strategy code to use local database instead of YFData.download.
    DataService is pre-imported in the execution environment.

    This replaces:
    - vbt.YFData.download(...) with DataService.get_ohlcv_data(ticker, start, end)
    - data.get('Column') with data['Column']
    - Removes 'from app.services.data_service import DataService' since it's pre-imported
    """
    modified = code

    # Remove the import statement if present (DataService is already available)
    modified = re.sub(
        r"from\s+app\.services\.data_service\s+import\s+DataService\s*\n?",
        "",
        modified
    )

    # Extract ticker from the download call
    ticker_match = re.search(r"vbt\.YFData\.download\(\s*['\"](\w+)['\"]", modified)
    if not ticker_match:
        # Try alternate format: YFData.download
        ticker_match = re.search(r"YFData\.download\(\s*['\"](\w+)['\"]", modified)

    if ticker_match:
        ticker = ticker_match.group(1).upper()

        # Replace the YFData.download call with DataService call
        # Match multi-line download calls
        modified = re.sub(
            r"\w+\s*=\s*vbt\.YFData\.download\([^)]+(?:\([^)]*\)[^)]*)*\)",
            f"data = DataService.get_ohlcv_data('{ticker}', start, end)",
            modified,
            flags=re.DOTALL
        )

        # Also try without vbt. prefix
        modified = re.sub(
            r"\w+\s*=\s*YFData\.download\([^)]+(?:\([^)]*\)[^)]*)*\)",
            f"data = DataService.get_ohlcv_data('{ticker}', start, end)",
            modified,
            flags=re.DOTALL
        )

    # Replace data.get('Column') with data['Column']
    modified = re.sub(
        r"data\.get\(['\"](\w+)['\"]\)",
        r"data['\1']",
        modified
    )

    return modified


def generate_strategy_code(prompt: str, tickers: List[str], start_date: str, end_date: str) -> tuple[Optional[str], Optional[str]]:
    """
    Generates strategy code using local LLM.
    Returns: (code, error_message)
    """
    if client is None:
        return None, "Local LLM client not initialized. Check that the model server is running on port 11434."

    # Verify LLM is responsive before starting
    ok, error = verify_llm_connection()
    if not ok:
        return None, f"LLM server not responding: {error}. Ensure the model '{MODEL_NAME}' is loaded and ready."

    user_msg = f"""
    Create a vectorbt strategy code for: "{prompt}".
    Target Tickers: {tickers}
    Date Range: {start_date} to {end_date}

    IMPORTANT: Return ONLY the complete Python code wrapped in a markdown python code block (```python ... ```).
    Do NOT include any explanation text before or after the code.
    """

    logger.info("Generating strategy for prompt: %s...", prompt[:100])

    try:
        import time
        start_time = time.time()
        logger.info("Starting LLM request for strategy generation with model '%s'...", MODEL_NAME)

        # Build enhanced system prompt with lessons learned
        enhanced_prompt = get_enhanced_system_prompt()

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": enhanced_prompt},
                {"role": "user", "content": user_msg}
            ],
            temperature=0,
            max_tokens=MAX_TOKENS,
            timeout=REQUEST_TIMEOUT,
        )
        elapsed = time.time() - start_time
        logger.info("LLM request completed in %.2fs", elapsed)

        content = response.choices[0].message.content
        if content is None:
            return None, "LLM returned empty response."
        logger.debug("Raw LLM response (first 500 chars): %s...", content[:500])

        code = extract_code_block(content)

        # Handle case where extract_code_block returns None (empty or no code found)
        if code is None:
            logger.warning("extract_code_block returned None. Raw content: %s...", content[:1000])
            return None, "Generated code is empty or malformed. Please try again with a clearer prompt."

        logger.debug("Extracted code (first 500 chars): %s...", code[:500])

        # Validate that extracted code is valid Python before returning
        import ast
        try:
            ast.parse(code)
        except SyntaxError as e:
            logger.error("Extracted code has syntax error: %s", e)
            logger.error("Problematic code:\n%s", code[:1000])
            return None, f"Generated code has invalid Python syntax: {e}. The LLM may have included explanatory text. Please try again with a clearer prompt."

        # Transform code to use local database if LLM used YFData.download
        code = transform_code_for_local_data(code)

        # Ensure generated dates match the requested range
        code = code.replace("{{START_DATE}}", start_date)
        code = code.replace("{{END_DATE}}", end_date)
        # Also catch common hardcoded date patterns the LLM might have used
        code = re.sub(
            r"start\s*=\s*['\"]\d{4}-\d{2}-\d{2}['\"]",
            f"start = '{start_date}'",
            code
        )
        code = re.sub(
            r"end\s*=\s*['\"]\d{4}-\d{2}-\d{2}['\"]",
            f"end = '{end_date}'",
            code
        )

        return code, None
    except Exception as e:
        error_str = str(e)
        logger.error("ERROR in generate_strategy_code: %s", error_str)

        # Provide more helpful error messages for common issues
        if "timed out" in error_str.lower() or "timeout" in error_str.lower():
            return None, f"LLM request timed out after {REQUEST_TIMEOUT}s. The model '{MODEL_NAME}' may be too slow or overloaded. Try: 1) Using a lighter model, 2) Checking Ollama logs with 'ollama ps', 3) Restarting Ollama service"
        elif "connection" in error_str.lower():
            return None, f"Cannot connect to Ollama at {LOCAL_API_BASE}. Ensure Ollama is running and the model '{MODEL_NAME}' is loaded."
        else:
            return None, error_str


def fix_strategy_code(current_code: str, error_context: str) -> str:
    """
    Fix strategy code based on error message or full error context.

    Args:
        current_code: The code that failed
        error_context: Error message string or full structured error context
            including category, line numbers, stdout, traceback, etc.

    Returns:
        Fixed code string, or original code if fix failed
    """
    if client is None:
        logger.error("ERROR: Client is None in fix_strategy_code")
        return current_code

    # Check for VBT comparison error and add specific guidance
    vbt_hint = ""
    if any(k in error_context.lower() for k in ("cannot join with no overlapping index names", "operands are not aligned", "can only compare identically-labeled", "no attribute 'gt'", "no attribute 'lt'", "combine_logic", "jitted")):
        vbt_hint = """

CRITICAL: This project uses vectorbt 1.0.0. The `.vbt.gt()/.lt()` accessors, `vbt.combine_logic()`, and `jitted=True` DO NOT EXIST in this version.
Fix the code to use plain pandas operators on broadcast operands:
- Call parameterized indicators with `.run()`: `fast_ma = vbt.MA.run(close, window=fast_window).ma`
- Define the `_bc(s, ref)` broadcast helper (see SYSTEM PROMPT rule #7) and broadcast every non-parameterized operand against the parameterized one.
- Use plain operators: `entries = (ef_bc > es_bc) & (close_bc > ef_bc)`
- Pass `broadcast_kwargs={'keep_pd': True}` to `vbt.Portfolio.from_signals(...)` and do NOT pass `jitted=True`.
"""

    # Try to find a matching lesson for additional guidance
    lesson_hint = ""
    try:
        lesson = _get_lessons_store().find_match(error_context)
        if lesson:
            lesson_hint = f"""

PREVIOUS FIX FOR SIMILAR ERROR ({lesson['error_signature']}):
{lesson['fix_description']}
"""
            if lesson.get("example_after"):
                lesson_hint += f"Example: {lesson['example_after']}\n"
    except Exception as e:
        logger.debug("Could not lookup lesson: %s", e)

    user_msg = f"""
The following vectorbt code failed to run:

```python
{current_code}
```

Error Context:
{error_context}
{vbt_hint}{lesson_hint}

Please fix the code. Return ONLY the full valid python code.
"""

    try:
        enhanced_prompt = get_enhanced_system_prompt()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": enhanced_prompt},
                {"role": "user", "content": user_msg}
            ],
            temperature=0,
            max_tokens=MAX_TOKENS,
            timeout=REQUEST_TIMEOUT,
        )
        content = response.choices[0].message.content
        if content is None:
            return current_code
        code = extract_code_block(content)
        if code is None:
            logger.warning("fix_strategy_code: extract_code_block returned None. Raw content: %s...", content[:1000])
            return current_code
        # Transform code to use local database if LLM used YFData.download
        code = transform_code_for_local_data(code)
        return code
    except Exception as e:
        logger.error("ERROR in fix_strategy_code: %s", e)
        return current_code


def chat_about_code(code: str, messages: List[Dict[str, str]]) -> tuple[Optional[str], Optional[str]]:
    """
    Chat about the strategy code using local LLM.
    Takes the current code and a list of chat messages.
    Returns: (response, error_message)
    """
    if client is None:
        return None, "Local LLM client not initialized. Check that the model server is running on port 11434."

    # Build messages with code context
    chat_messages = [
        {"role": "system", "content": CHAT_SYSTEM_PROMPT + "\n\n```python\n" + code + "\n```"}
    ]

    # Add conversation history
    for msg in messages:
        chat_messages.append(msg)

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=chat_messages,  # type: ignore[arg-type]
            temperature=0.7,
            max_tokens=MAX_TOKENS,
            timeout=REQUEST_TIMEOUT,
        )
        content = response.choices[0].message.content
        if content is None:
            return None, "LLM returned empty response."
        return content, None
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("ERROR in chat_about_code: %s", e)
        return None, str(e)


def is_llm_available() -> bool:
    """Check if LLM features are available."""
    if client is None:
        return False
    # Also verify connection is working
    ok, error = verify_llm_connection()
    return ok


def get_model_name() -> str:
    """Get the name of the LLM model being used."""
    return MODEL_NAME


def get_llm_client() -> tuple[Optional["OpenAI"], str]:
    """Return the shared LLM client and model name. Reuses the module-level
    client configured at import time; no duplicate retry/timeout logic.
    Returns (None, model_name) if the client failed to initialize.
    """
    return client, MODEL_NAME
