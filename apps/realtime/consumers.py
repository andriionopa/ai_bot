from channels.generic.websocket import AsyncJsonWebsocketConsumer


class LogConsumer(AsyncJsonWebsocketConsumer):
    group_name = "logs"

    async def connect(self):
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def log_message(self, event):
        await self.send_json(event["payload"])

