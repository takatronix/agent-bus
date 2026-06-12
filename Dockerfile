FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV AGENT_BUS_HOST=0.0.0.0
ENV AGENT_BUS_PORT=8765
ENV AGENT_BUS_DB=/data/agent-bus.sqlite3
ENV AGENT_BUS_ARTIFACT_DIR=/data/artifacts

WORKDIR /app
COPY . /app
RUN chmod +x /app/bin/agent-bus /app/bin/agentctl /app/bin/agent-bus-mcp

VOLUME ["/data"]
EXPOSE 8765

CMD ["/app/bin/agent-bus"]
