from pymodaq.utils.config import Config
from pymodaq.utils import data as data_mod
from pymodaq.utils import gui_utils as gutils
from pymodaq.utils import daq_utils as utils
from pymodaq.utils.scanner.scanner import Scanner
from pymodaq.utils.managers.modules_manager import ModulesManager
from pymodaq.utils.h5modules import module_saving
from pymodaq.extensions.daq_scan import DAQScan, DAQScanAcquisition, ScanDataTemp
from pyqtgraph.parametertree import Parameter, ParameterTree
from pymodaq.utils.parameter import pymodaq_ptypes
from qtpy import QtWidgets, QtCore
from qtpy.QtCore import QThread

import numpy as np

config = utils.load_config()
logger = utils.set_logger(utils.get_module_name(__file__))

EXTENSION_NAME = 'Custom TA Scanner'
CLASS_NAME = 'mydaqscan'


class mydaqscan(DAQScan):
    # list of dicts enabling the settings tree on the user interface
    params = DAQScan.params + []
    
    def __init__(self, dockarea, dashboard):
        super().__init__(dockarea, dashboard)
    
    #Copy pasted from parent class, with scan_acquisition changed for my own class myDAQScanAcquisition
    def start_scan(self):
        """
            Start an acquisition calling the set_scan function.
            Emit the command_DAQ signal "start_acquisition".

            See Also
            --------
            set_scan
        """
        self.ui.display_status('Starting acquisition')
        self.dashboard.overshoot = False
        #deactivate double_clicked
        if self.ui.is_action_checked('move_at'):
            self.ui.get_action('move_at').trigger()

        res = self.set_scan()
        if res:
            # deactivate module controls using remote_control
            if hasattr(self.dashboard, 'remote_manager'):
                remote_manager = getattr(self.dashboard, 'remote_manager')
                remote_manager.activate_all(False)

            self.module_and_data_saver.h5saver = self.h5saver
            new_scan = self.module_and_data_saver.get_last_node().attrs['scan_done'] # get_last_node
            scan_node = self.module_and_data_saver.get_set_node(new=new_scan)
            self.save_metadata(scan_node, 'scan_info')

            self._init_live()

            # mandatory to deal with multithreads
            if self.scan_thread is not None:
                self.command_daq_signal.disconnect()
                if self.scan_thread.isRunning():
                    self.scan_thread.terminate()
                    while not self.scan_thread.isFinished():
                        QThread.msleep(100)
                    self.scan_thread = None

            self.scan_thread = QThread()

            scan_acquisition = myDAQScanAcquisition(self.settings, self.scanner, self.h5saver.settings,
                                                  self.modules_manager,
                                                  module_saver=self.module_and_data_saver)
            
            if config['scan']['scan_in_thread']:
                scan_acquisition.moveToThread(self.scan_thread)
            self.command_daq_signal[utils.ThreadCommand].connect(scan_acquisition.queue_command)
            scan_acquisition.scan_data_tmp[ScanDataTemp].connect(self.save_temp_live_data)
            scan_acquisition.status_sig[list].connect(self.thread_status)

            self.scan_thread.scan_acquisition = scan_acquisition
            self.scan_thread.start()

            self.ui.set_action_enabled('ini_positions', False)
            self.ui.set_action_enabled('start', False)
            self.ui.set_scan_done(False)
            if not self.settings['plot_options', 'plot_at_each_step']:
                self.live_timer.start(self.settings['plot_options', 'refresh_live'])
            self.command_daq_signal.emit(utils.ThreadCommand('start_acquisition'))
            self.ui.set_permanent_status('Running acquisition')
            logger.info('Running acquisition')


class myDAQScanAcquisition(DAQScanAcquisition):
    
    def __init__(self, scan_settings: Parameter = None, scanner: Scanner = None,
                 h5saver_settings: Parameter = None, modules_manager: ModulesManager = None,
                 module_saver: module_saving.ScanSaver = None):
        DAQScanAcquisition.__init__(self, scan_settings, scanner, h5saver_settings, modules_manager, module_saver)

    
    def start_acquisition(self):
        ###Copy pasted from parent class
        try:
            #todo hoaw to apply newlayout to adaptive mode?

            self.modules_manager.connect_actuators()
            self.modules_manager.connect_detectors()
            
            #take backgrounds at the beginning of each scan
            print(self.modules_manager._detectors)
            #_tadetector = self.modules_manager.get_mod_from_name('tadetector', mod = 'det')
            #_tadetector.take_background()
            
            self.stop_scan_flag = False
            
            Naxes = self.scanner.n_axes
            scan_type = self.scanner.scan_type
            self.navigation_axes = self.scanner.get_nav_axes()
            self._actual_nav_axes = self.scanner.get_nav_axes()     #1st modif : init actual axes
            for actual_axis in self._actual_nav_axes:
                actual_axis.label = 'measured_' + actual_axis.label
                actual_axis.data = self.scanner.positions.flatten()
            self.status_sig.emit(["Update_Status", "Acquisition has started", 'log'])

            self.timeout_scan_flag = False
            for ind_average in range(self.Naverage):
                self.ind_average = ind_average
                self.ind_scan = -1
                while True:
                    self.ind_scan += 1
                    if not self.isadaptive:
                        if self.ind_scan >= len(self.scanner.positions):
                            break
                        positions = self.scanner.positions_at(self.ind_scan)  # get positions
                    else:
                        pass
                        #todo update for v4
                        # positions = learner.ask(1)[0][-1]  # next point to probe
                        # if self.scanner.scan_type == 'Tabular':  # translate normalized curvilinear position to real coordinates
                        #     self.curvilinear = positions
                        #     length = 0.
                        #     for v in self.scanner.vectors:
                        #         length += v.norm()
                        #         if length >= self.curvilinear:
                        #             vec = v
                        #             frac_curvilinear = (self.curvilinear - (length - v.norm())) / v.norm()
                        #             break
                        #
                        #     position = (vec.vectorize() * frac_curvilinear).translate_to(vec.p1()).p2()
                        #     positions = [position.x(), position.y()]

                    self.status_sig.emit(["Update_scan_index", [self.ind_scan, ind_average]])

                    if self.stop_scan_flag or self.timeout_scan_flag:
                        break

                    #move motors of modules and wait for move completion
                    positions = self.modules_manager.order_positions(self.modules_manager.move_actuators(positions))

                    QThread.msleep(self.scan_settings['time_flow', 'wait_time_between'])

                    #grab datas and wait for grab completion
                    self.det_done(self.modules_manager.grab_datas(positions=positions), positions)

                    if self.isadaptive:
                        #todo update for v4
                        # det_channel = self.modules_manager.get_selected_probed_data()
                        # det, channel = det_channel[0].split('/')
                        # if self.scanner.scan_type == 'Tabular':
                        #     self.curvilinear_array.append(np.array([self.curvilinear]))
                        #     new_positions = self.curvilinear
                        # elif self.scanner.scan_type == 'Scan1D':
                        #     new_positions = positions[0]
                        # else:
                        #     new_positions = positions[:]
                        # learner.tell(new_positions, self.modules_manager.det_done_datas[det]['data0D'][channel]['data'])
                        pass

                    # daq_scan wait time
                    QThread.msleep(self.scan_settings.child('time_flow', 'wait_time').value())
                    
                #2nd modif
                self.module_and_data_saver.add_nav_axes(self._actual_nav_axes)
                
            self.h5saver.flush()
            self.modules_manager.connect_actuators(False)
            self.modules_manager.connect_detectors(False)

            self.status_sig.emit(["Update_Status", "Acquisition has finished", 'log'])
            self.status_sig.emit(["Scan_done"])

        except Exception as e:
            logger.exception(str(e))
            # self.status_sig.emit(["Update_Status", getLineInfo() + str(e), 'log'])


    def det_done(self, det_done_datas: data_mod.DataToExport, positions):
        ###Copy pasted from the parent class.
        try:
            indexes = self.scanner.get_indexes_from_scan_index(self.ind_scan)
            if self.Naverage > 1:
                indexes = [self.ind_average] + list(indexes)
            indexes = tuple(indexes)
            if self.ind_scan == 0:
                nav_axes = self.scanner.get_nav_axes()
                if self.Naverage > 1:
                    for nav_axis in nav_axes:
                        nav_axis.index += 1
                    nav_axes.append(data_mod.Axis('Average', data=np.linspace(0, self.Naverage - 1, self.Naverage),
                                                  index=0))
                #self.module_and_data_saver.add_nav_axes(nav_axes)
            for actual_nav_axis, pos in zip(self._actual_nav_axes, positions):
                actual_nav_axis.data[self.ind_scan] = pos.data[0][0]  #my modif
            self.module_and_data_saver.add_data(indexes=indexes, distribution=self.scanner.distribution)

            #todo related to adaptive (solution lies along the Enlargeable data saver)
            if self.isadaptive:
                for ind_ax, nav_axis in enumerate(self.navigation_axes):
                    nav_axis.append(np.array(positions[ind_ax]))

            self.det_done_flag = True

            full_names: list = self.scan_settings['plot_options', 'plot_0d']['selected'][:]
            full_names.extend(self.scan_settings['plot_options', 'plot_1d']['selected'][:])
            data_temp = det_done_datas.get_data_from_full_names(full_names, deepcopy=False)
            data_temp = data_temp.get_data_with_naxes_lower_than(2-len(indexes))  # maximum Data2D included nav indexes

            self.scan_data_tmp.emit(ScanDataTemp(self.ind_scan, indexes, data_temp))
            
        except Exception as e:
            logger.exception(str(e))
    
def main():
    pass

if __name__ == '__main__':
    main()


