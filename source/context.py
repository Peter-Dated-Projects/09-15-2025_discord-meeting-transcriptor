import discord
from source.server.server import ServerManager
from source.services.manager import ServicesManager


# -------------------------------------------------------------- #
# Context Class
# -------------------------------------------------------------- #


class Context:
    def __init__(
        self, server_manager: ServerManager, services_manager: ServicesManager, bot: discord.Bot
    ):
        self.server_manager = server_manager
        self.services_manager = services_manager
        self.bot = bot
