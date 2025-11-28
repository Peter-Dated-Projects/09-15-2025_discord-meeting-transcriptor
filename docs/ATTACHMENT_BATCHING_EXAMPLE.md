# Attachment Batching Example

## Scenario: User sends multiple messages with attachments while bot is thinking

### Timeline

```
T=0s   User: "@Bot analyze this data"
       Attachments: [report.pdf]
       → Bot starts processing (status: THINKING)
       → Message added to conversation history with attachment

T=2s   User: "also look at this chart"
       Attachments: [chart.png]
       → Bot still thinking
       → Message QUEUED with attachment
       
T=4s   User: "and check this article: https://example.com/article"
       Attachments: [url: https://example.com/article]
       → Bot still thinking
       → Message QUEUED with attachment
       
T=6s   User: "here's another view"
       Attachments: [graph.jpg]
       → Bot still thinking
       → Message QUEUED with attachment

T=8s   Bot: Finishes initial response
       → Status changes to PROCESSING_QUEUE
       → Processes all 3 queued messages together
       → Each message's attachments preserved individually

T=10s  Bot: Sends comprehensive response addressing all messages and attachments
       → Status changes to IDLE
```

## What the Bot Sees

### Initial Message (T=0s)
```python
Message(
    created_at=datetime(2025, 11, 26, 14, 30, 0),
    message_type=MessageType.CHAT,
    message_content="analyze this data",
    requester="123456789",
    attachments=[
        {
            "type": "file",
            "url": "https://cdn.discordapp.com/.../report.pdf",
            "filename": "report.pdf",
            "content_type": "application/pdf",
            "size": 524288
        }
    ]
)
```

### Batched Processing
When the queue is processed, all 3 messages are added to conversation history individually, then sent to LLM together.

## Benefits of Batching

1. **Efficiency** - One LLM call instead of three
2. **Context** - Bot sees all related messages together
3. **Coherent Response** - Single comprehensive answer
4. **Resource Management** - Better GPU utilization
5. **User Experience** - Avoids rapid-fire responses
