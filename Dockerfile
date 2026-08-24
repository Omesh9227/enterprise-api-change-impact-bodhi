FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV MCP_HOST=0.0.0.0 
CMD ["python","mcp_server.py"]
