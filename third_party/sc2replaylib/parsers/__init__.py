from third_party.abc import ABCMeta, abstractmethod

from third_party.sc2replaylib import Sc2replaylibException

class Parser:
	__metaclass__ = ABCMeta

	@abstractmethod
	def parse(self):
		pass

class ParserException(Sc2replaylibException):
	pass
