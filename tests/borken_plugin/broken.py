from errbot import BotPlugin, botcmd

import borken  # fails on purpose


class Broken(BotPlugin):

    @botcmd
    def hello(self, msg, args):
        """ this command says hello """
        return "Hello World !"
