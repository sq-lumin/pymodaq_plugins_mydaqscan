from typing import List, Tuple, Any
import re
import numpy as np
from pymodaq.utils.data import Axis, DataDistribution
from pymodaq.utils.logger import set_logger, get_module_name
from pymodaq.utils import math_utils as mutils
from pymodaq.utils import config as configmod
from pymodaq.utils.plotting.scan_selector import Selector
from pymodaq.utils.scanner.scanners._1d_scanners import Scan1DBase
from pymodaq.utils.scanner.scan_factory import ScannerFactory, ScannerBase, ScanParameterManager

logger = set_logger(get_module_name(__file__))
config = configmod.Config()

@ScannerFactory.register()
class Scan1DCustom(Scan1DBase):
    """ My personnal scan between start and stop values with steps of length defined in the step setting. asks actuator for actual positions"""

    scan_subtype = 'Custom TA'
    params = [
        {'title': 'Start:', 'name': 'start', 'type': 'float', 'value': 0.},
        {'title': 'Stop:', 'name': 'stop', 'type': 'float', 'value': 1.},
        {'title': 'Step:', 'name': 'step', 'type': 'float', 'value': 0.1}
        ]
    n_axes = 1
    distribution = DataDistribution['uniform']

    def __init__(self, actuators: List = None, **_ignored):
        ScannerBase.__init__(self, actuators=actuators)
        print(self.actuators)
        print(self.actuators[0].get_actuator_value())

    def set_scan(self):
        self.positions = mutils.linspace_step(self.settings['start'], self.settings['stop'],
                                              self.settings['step'])
        self.get_info_from_positions(self.positions)

    def set_settings_titles(self):
        if len(self.actuators) == 1:
            self.settings.child('start').setOpts(title=f'{self.actuators[0].title} start:')
            self.settings.child('stop').setOpts(title=f'{self.actuators[0].title} stop:')
            self.settings.child('step').setOpts(title=f'{self.actuators[0].title} step:')

    def evaluate_steps(self) -> int:
        n_steps = int(np.abs((self.settings['stop'] - self.settings['start']) / self.settings['step']) + 1)
        return n_steps

    def update_from_scan_selector(self, scan_selector: Selector):
        coordinates = scan_selector.get_coordinates()
        if coordinates.shape == (2, 2) or coordinates.shape == (2, 1):
            self.settings.child('start').setValue(coordinates[0, 0])
            self.settings.child('stop').setValue(coordinates[1, 0])
    
def main():
    pass

if __name__ == '__main__':
    main()


