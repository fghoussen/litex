from migen.fhdl.std import *
from migen.bus import wishbone
from migen.bus.transactions import *
from migen.sim.generic import run_simulation

from misoclib.ethmac import EthMAC
from misoclib.ethmac.phy import loopback

class WishboneMaster:
	def __init__(self, obj):
		self.obj = obj
		self.dat = 0

	def write(self, adr, dat):
		self.obj.cyc = 1
		self.obj.stb = 1
		self.obj.adr = adr
		self.obj.we = 1
		self.obj.sel = 0xF
		self.obj.dat_w = dat
		while self.obj.ack == 0:
			yield
		self.obj.cyc = 0
		self.obj.stb = 0
		yield

	def read(self, adr):
		self.obj.cyc = 1
		self.obj.stb = 1
		self.obj.adr = adr
		self.obj.we = 0
		self.obj.sel = 0xF
		self.obj.dat_w = 0
		while self.obj.ack == 0:
			yield
		self.dat = self.obj.dat_r
		self.obj.cyc = 0
		self.obj.stb = 0
		yield

class SRAMReaderDriver:
	def __init__(self, obj):
		self.obj = obj

	def start(self, slot, length):
		self.obj._slot.storage = slot
		self.obj._length.storage = length
		self.obj._start.re = 1
		yield
		self.obj._start.re = 0
		yield

	def wait_done(self):
		while self.obj.ev.done.pending == 0:
			yield

	def clear_done(self):
		self.obj.ev.done.clear = 1
		yield
		self.obj.ev.done.clear = 0
		yield

class TB(Module):
	def __init__(self):
		self.submodules.ethphy = loopback.LoopbackPHY()
		self.submodules.ethmac = EthMAC(phy=self.ethphy, with_hw_preamble_crc=True)

		# use sys_clk for each clock_domain
		self.clock_domains.cd_eth_rx = ClockDomain()
		self.clock_domains.cd_eth_tx = ClockDomain()
		self.comb += [
			self.cd_eth_rx.clk.eq(ClockSignal()),
			self.cd_eth_rx.rst.eq(ResetSignal()),
			self.cd_eth_tx.clk.eq(ClockSignal()),
			self.cd_eth_tx.rst.eq(ResetSignal()),
		]

	def gen_simulation(self, selfp):
		selfp.cd_eth_rx.rst = 1
		selfp.cd_eth_tx.rst = 1
		yield
		selfp.cd_eth_rx.rst = 0
		selfp.cd_eth_tx.rst = 0

		wishbone_master = WishboneMaster(selfp.ethmac.bus)
		sram_reader_driver = SRAMReaderDriver(selfp.ethmac.sram_reader)

		sram_writer_slots_offset = [0x000, 0x200]
		sram_reader_slots_offset = [0x400, 0x600]

		length = 1500-2

		payload = [i % 0xFF for i in range(length)] + [0, 0, 0, 0]

		errors = 0

		for slot in range(2):
			# fill tx memory
			for i in range(length//4+1):
				dat = 0
				dat |= payload[4*i+0] << 24
				dat |= payload[4*i+1] << 16
				dat |= payload[4*i+2] << 8
				dat |= payload[4*i+3] << 0
				yield from wishbone_master.write(sram_reader_slots_offset[slot]+i, dat)

			# send tx data & wait
			yield from sram_reader_driver.start(slot, length)
			yield from sram_reader_driver.wait_done()
			yield from sram_reader_driver.clear_done()

			# get rx data (loopback on PHY Model)
			rx_dat = []
			for i in range(length//4+1):
				yield from wishbone_master.read(sram_writer_slots_offset[slot]+i)
				dat = wishbone_master.dat
				rx_dat.append((dat >> 24) & 0xFF)
				rx_dat.append((dat >> 16) & 0xFF)
				rx_dat.append((dat >> 8) & 0xFF)
				rx_dat.append((dat >> 0) & 0xFF)

			# check rx data
			for i in range(length):
				#print("{:02x} / {:02x}".format(rx_dat[i], payload[i]))
				if rx_dat[i] != payload[i]:
					errors += 1

		for i in range(200):
			yield
		#print(selfp.ethmac.sram_reader._length.storage)

		print("Errors : {}".format(errors))

if __name__ == "__main__":
	run_simulation(TB(), ncycles=16000, vcd_name="my.vcd", keep_files=True)