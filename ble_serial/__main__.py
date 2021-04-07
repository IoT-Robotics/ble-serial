import logging, sys, argparse, time, asyncio
from ble_serial.serial.linux_pty import UART
from ble_serial.ble_interface import BLE_interface
from ble_serial.fs_log import FS_log, Direction
from bleak.exc import BleakError

class Main():
    def __init__(self):
        parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter, 
            description='Create virtual serial ports from BLE devices.')
        
        parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
            help='Increase verbosity to log all data going through')
        parser.add_argument('-d', '--dev', dest='device', required=True,
            help='BLE device address to connect (hex format, can be seperated by colons)')
        parser.add_argument('-t', '--address-type', dest='addr_type', required=False, choices=['public', 'random'], default='public',
            help='BLE address type, either public or random')
        parser.add_argument('-i', '--interface', dest='adapter', required=False, default='hci0',
            help='BLE host adapter number to use')
        parser.add_argument('-m', '--mtu', dest='mtu', required=False, default=20, type=int,
            help='Max. bluetooth packet data size in bytes used for sending')
        parser.add_argument('-w', '--write-uuid', dest='write_uuid', required=False,
            help='The GATT chracteristic to write the serial data, you might use "scan.py -d" to find it out')
        parser.add_argument('-l', '--log', dest='filename', required=False,
            help='Enable optional logging of all bluetooth traffic to file')
        parser.add_argument('-b', '--binary', dest='binlog', required=False, action='store_true',
            help='Log data as raw binary, disable transformation to hex. Works only in combination with -l')
        parser.add_argument('-p', '--port', dest='port', required=False, default='/tmp/ttyBLE',
            help='Symlink to virtual serial port')
        parser.add_argument('-r', '--read-uuid', dest='read_uuid', required=False,
            help='The GATT characteristic to subscribe to notifications to read the serial data')
        self.args = parser.parse_args()

        logging.basicConfig(
            format='%(asctime)s.%(msecs)03d | %(levelname)s | %(filename)s: %(message)s', 
            datefmt='%H:%M:%S',
            level=logging.DEBUG if self.args.verbose else logging.INFO
        )
        logging.getLogger('bleak').level = logging.INFO

        try:
            asyncio.run(self.run())
        # KeyboardInterrupt causes bluetooth to disconnect, but still a exception would be printed here
        except KeyboardInterrupt as e:
            logging.debug('Exit due to KeyboardInterrupt')

    async def run(self):
        args = self.args
        loop = asyncio.get_event_loop()
        loop.set_exception_handler(self.excp_handler)
        try:
            self.uart = UART(args.port, loop, args.mtu)
            self.bt = BLE_interface()
            if args.filename:
                self.log = FS_log(args.filename, args.binlog)
                self.bt.set_receiver(self.log.middleware(Direction.BLE_IN, self.uart.queue_write))
                self.uart.set_receiver(self.log.middleware(Direction.BLE_OUT, self.bt.queue_send))
            else:
                self.bt.set_receiver(self.uart.queue_write)
                self.uart.set_receiver(self.bt.queue_send)

            self.uart.start()
            await self.bt.start(args.device, args.addr_type, args.adapter, args.write_uuid, args.read_uuid)
            logging.info('Running main loop!')
            self.main_loop = asyncio.gather(self.bt.send_loop(), self.uart.run_loop())
            await self.main_loop

        except BleakError as e:
            logging.warning(f'Bluetooth connection failed: {e}')
        ### KeyboardInterrupts are now received on asyncio.run()
        # except KeyboardInterrupt:
        #     logging.info('Keyboard interrupt received')
        except Exception as e:
            logging.error(f'Unexpected Error: {e}')
        finally:
            logging.warning('Shutdown initiated')
            if hasattr(self, 'uart'):
                self.uart.remove()
            if hasattr(self, 'bt'):
                await self.bt.disconnect()
            if hasattr(self, 'log'):
                self.log.finish()
            logging.info('Shutdown complete.')


    def excp_handler(self, loop: asyncio.AbstractEventLoop, context):
        # Handles exception from other tasks (inside bleak disconnect, etc)
        # loop.default_exception_handler(context)
        logging.debug(f'Asyncio execption handler called {context["exception"]}')
        self.uart.stop_loop()
        self.bt.stop_loop()

if __name__ == '__main__':
    Main()