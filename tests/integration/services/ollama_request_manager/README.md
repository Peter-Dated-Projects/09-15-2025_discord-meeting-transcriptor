# Ollama Request Manager Integration Tests

This directory contains integration tests that interact with a **real Ollama instance**. These tests verify actual functionality rather than using mocks.

## Prerequisites

### 1. Ollama Must Be Running

Make sure Ollama is installed and running:

```bash
# Check if Ollama is running
curl http://localhost:11434/api/version

# Or start Ollama (if not running)
ollama serve
```

### 2. Pull Required Model

Pull the model specified in your `.env.local`:

```bash
# Check your OLLAMA_MODEL in .env.local (e.g., gpt-oss:20b)
ollama pull gpt-oss:20b

# Or use a smaller model for faster tests
ollama pull llama2
```

### 3. Environment Variables

The tests automatically load configuration from `.env.local`:

```bash
OLLAMA_HOST=localhost
OLLAMA_PORT=11434
OLLAMA_MODEL=gpt-oss:20b  # or your preferred model
```

## Running the Tests

### Run All Integration Tests

```bash
# From project root
pytest tests/integration/services/ollama_request_manager/ -v -s
```

The `-s` flag shows print statements for debugging.

### Run Specific Test Classes

```bash
# Test basic queries only
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestBasicQueries -v -s

# Test streaming
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestStreaming -v -s

# Test sessions
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestSessionManagement -v -s

# Test RAG
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestRAGContext -v -s

# Test JSON output
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestJSONOutput -v -s

# Test generation parameters
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestGenerationParameters -v -s
```

### Run Single Test

```bash
pytest tests/integration/services/ollama_request_manager/test_manager_integration.py::TestBasicQueries::test_simple_query -v -s
```

### Run with Coverage

```bash
pytest tests/integration/services/ollama_request_manager/ \
  --cov=source.services.ollama_request_manager.manager \
  --cov-report=html \
  -v -s
```

## Test Categories

### 1. **TestBasicQueries**
- Simple prompt queries
- Message history
- System prompts
- Longer responses
- Token counting

### 2. **TestStreaming**
- Streaming responses
- Statistics updates during streaming

### 3. **TestSessionManagement**
- Multi-turn conversations
- Session memory
- Multiple independent sessions

### 4. **TestRAGContext**
- Query with documents
- Query with extra context
- Multi-source RAG (context + documents)

### 5. **TestJSONOutput**
- JSON object generation
- JSON array generation
- Parsing validation

### 6. **TestGenerationParameters**
- Temperature variation (low vs high)
- Max tokens (num_predict) limits
- Stop sequences
- Seed reproducibility

### 7. **TestModelManagement**
- List available models
- Statistics tracking

### 8. **TestErrorHandling**
- Invalid model names
- Timeout handling

### 9. **TestPerformance**
- Concurrent queries
- Response timing
- Performance metrics

## Test Output

Tests include print statements showing:
- ✓ Response content
- ✓ Token counts
- ✓ Timing information
- ✓ Session statistics
- ✓ Model information

Example output:
```
✓ Simple query result: 4
✓ Message history result: Your name is Alice.
✓ Longer response (87 tokens): 1. Python - Versatile...
✓ Streaming test complete (15 chunks)
✓ Session has 4 messages
```

## Tips

### Using Different Models

Edit `.env.local` to test with different models:

```bash
# Faster, smaller model for quick tests
OLLAMA_MODEL=llama2

# Larger, more capable model
OLLAMA_MODEL=gpt-oss:20b

# Code-specialized model
OLLAMA_MODEL=codellama
```

### Skipping Tests

If Ollama is not available, tests will automatically skip:

```
SKIPPED [1] tests/integration/services/ollama_request_manager/test_manager_integration.py:40: 
Ollama server not available at localhost:11434
```

### Performance Considerations

- Tests make **real API calls** and can take several minutes
- Each test waits for Ollama to generate responses
- Larger models are slower but more capable
- Use smaller models (llama2) for faster test runs
- Consider running specific test classes during development

### Debugging

Use `-s` flag to see print output:

```bash
pytest tests/integration/services/ollama_request_manager/ -v -s
```

Use `--log-cli-level=DEBUG` for detailed logs:

```bash
pytest tests/integration/services/ollama_request_manager/ -v -s --log-cli-level=DEBUG
```

## Continuous Integration

For CI/CD pipelines, you can:

1. **Skip integration tests** by default:
   ```bash
   pytest tests/unit/  # Only unit tests
   ```

2. **Run with Ollama in Docker**:
   ```bash
   docker run -d -p 11434:11434 ollama/ollama
   docker exec ollama ollama pull llama2
   pytest tests/integration/services/ollama_request_manager/
   ```

3. **Use markers**:
   ```python
   @pytest.mark.integration
   ```
   Then run:
   ```bash
   pytest -m "not integration"  # Skip integration tests
   pytest -m integration        # Run only integration tests
   ```

## Troubleshooting

### "Ollama server not available"

```bash
# Start Ollama
ollama serve

# Verify it's running
curl http://localhost:11434/api/version
```

### "Model not found"

```bash
# Pull the model first
ollama pull llama2

# Or change OLLAMA_MODEL in .env.local
```

### Tests timeout

- Increase timeout in tests
- Use smaller model (llama2 instead of larger models)
- Reduce `num_predict` values

### Slow tests

- Use `llama2` or `tinyllama` for faster responses
- Reduce `num_predict` limits
- Run specific test classes instead of all tests
- Consider running tests in parallel (with caution for resource usage)

## Contributing

When adding new integration tests:

1. Keep tests focused and independent
2. Use low temperatures (0.1-0.3) for deterministic tests
3. Set reasonable `num_predict` limits
4. Include print statements for debugging
5. Handle Ollama unavailability gracefully
6. Document expected behavior in docstrings
