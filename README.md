## Run MCP Server Only (for Claude Custom + ngrok)

If you only want to run the MCP server and test tools directly:

1. Activate your virtual environment:

```bash
source .venv/bin/activate
```

2. Start the server over HTTP transport:

```bash
MCP_TRANSPORT=streamable-http python mcp_server.py
```

3. In a separate terminal, expose it with ngrok:

```bash
ngrok http 8000
```

4. Use the ngrok HTTPS URL in Claude Custom MCP server setup.

### Optional Security (Bearer Token Gate)

You can protect the MCP endpoint with a static bearer token.

Set these in `.env`:

```bash
MCP_AUTH_BEARER_TOKEN="replace-with-long-random-token"
MCP_AUTH_ISSUER_URL="https://your-auth-domain.example"
MCP_AUTH_RESOURCE_SERVER_URL="https://your-ngrok-domain.ngrok-free.dev"
MCP_AUTH_REQUIRED_SCOPES="mcp:access"
```

Notes:

- If `MCP_AUTH_BEARER_TOKEN` is empty, auth is disabled.
- If `MCP_AUTH_BEARER_TOKEN` is set, both `MCP_AUTH_ISSUER_URL` and `MCP_AUTH_RESOURCE_SERVER_URL` are required.
- This is token-gate security, not a full OAuth authorization server flow.
- For Claude custom connector OAuth fields, leave Client ID/Secret empty unless you implement a full OAuth provider.

### Test Tools Added

- `echo(message: str) -> str`: Returns the same message.
- `input_output(user_input: str, mode: str = "none") -> dict`: Returns input and transformed output.

Supported `mode` values:

- `none` (default): output equals input
- `upper`: output converted to uppercase
- `lower`: output converted to lowercase
# MCP Chat

MCP Chat is a command-line interface application that enables interactive chat capabilities with AI models through the Anthropic API. The application supports document retrieval, command-based prompts, and extensible tool integrations via the MCP (Model Control Protocol) architecture.

## Prerequisites

- Python 3.9+
- Anthropic API Key

## Setup

### Step 1: Configure the environment variables

1. Create or edit the `.env` file in the project root and verify that the following variables are set correctly:

```
ANTHROPIC_API_KEY=""  # Enter your Anthropic API secret key
```

### Step 2: Install dependencies

#### Option 1: Setup with uv (Recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer and resolver.

1. Install uv, if not already installed:

```bash
pip install uv
```

2. Create and activate a virtual environment:

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:

```bash
uv pip install -e .
```

4. Run the project

```bash
uv run main.py
```

#### Option 2: Setup without uv

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install anthropic python-dotenv prompt-toolkit "mcp[cli]==1.8.0"
```

3. Run the project

```bash
python main.py
```

## Usage

### Basic Interaction

Simply type your message and press Enter to chat with the model.

### Document Retrieval

Use the @ symbol followed by a document ID to include document content in your query:

```
> Tell me about @deposition.md
```

### Commands

Use the / prefix to execute commands defined in the MCP server:

```
> /summarize deposition.md
```

Commands will auto-complete when you press Tab.

## Development

### Adding New Documents

Edit the `mcp_server.py` file to add new documents to the `docs` dictionary.

### Implementing MCP Features

To fully implement the MCP features:

1. Complete the TODOs in `mcp_server.py`
2. Implement the missing functionality in `mcp_client.py`

### Linting and Typing Check

There are no lint or type checks implemented.
