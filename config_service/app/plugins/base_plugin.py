class BasePlugin:
    async def validate(self, config: dict):
        raise NotImplementedError()

    async def connect(self, config: dict):
        raise NotImplementedError()
