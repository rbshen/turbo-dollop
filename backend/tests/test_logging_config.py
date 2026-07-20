import logging

from logging_config import RedactApiKeyFilter, configure_logging


def _filtered_message(raw_message: str) -> str:
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1, msg=raw_message, args=(), exc_info=None
    )
    RedactApiKeyFilter().filter(record)
    return record.getMessage()


def test_redacts_apikey_in_the_middle_of_a_url():
    message = (
        'HTTP Request: GET https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=SECRET12345 "HTTP/1.1 200 OK"'
    )
    result = _filtered_message(message)
    assert "SECRET12345" not in result
    assert "apikey=REDACTED" in result
    assert "symbol=AAPL" in result  # other query params must survive untouched


def test_redacts_apikey_at_the_end_of_a_url():
    message = "GET https://financialmodelingprep.com/stable/profile?symbol=MSFT&apikey=ABCDEF999"
    result = _filtered_message(message)
    assert "ABCDEF999" not in result
    assert result.endswith("apikey=REDACTED")


def test_case_insensitive_apikey_param_name():
    message = "GET https://example.com/x?ApiKey=SHOULDNOTLEAK"
    result = _filtered_message(message)
    assert "SHOULDNOTLEAK" not in result


def test_message_without_apikey_is_left_unchanged():
    message = "Starting nightly fundamentals fetch for 500 tickers."
    result = _filtered_message(message)
    assert result == message


def test_configure_logging_writes_redacted_output_to_the_log_file(tmp_path):
    log_path = tmp_path / "test.log"
    configure_logging(log_path)

    fake_key_shaped_value = "FAKE0000TESTKEY0000PLACEHOLDER0"
    logging.getLogger("httpx").info(
        "HTTP Request: GET https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey=%s \"HTTP/1.1 200 OK\"",
        fake_key_shaped_value,
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text()
    assert fake_key_shaped_value not in content
    assert "apikey=REDACTED" in content
