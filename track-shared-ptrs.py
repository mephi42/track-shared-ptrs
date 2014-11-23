#!/usr/bin/env python
import gdb
import logging
import json
import os


def gdb_run():
    gdb.execute("run")


def gdb_continue():
    gdb.execute("continue")


def gdb_quit():
    gdb.execute("quit")


def parse_log_level(level):
    level = level.upper()
    if level == "DEBUG":
        return logging.DEBUG
    elif level == "INFO":
        return logging.INFO
    elif level == "WARNING":
        return logging.WARNING
    elif level == "ERROR":
        return logging.ERROR
    else:
        raise RuntimeError("Unexpected log level " + level)


class Backtrace:
    def __init__(self, type):
        self.type = type
        self.lines = []
        frame = gdb.newest_frame()
        while frame is not None:
            sal = frame.find_sal()
            filename = sal.symtab.filename
            line = sal.line
            location = filename + ":" + str(line)
            self.lines.append(str(frame.function()) + " at " + location)
            frame = frame.older()

    def export(self):
        return {
            "type": self.type,
            "lines": self.lines
        }


class SpCountedBase:
    CLASS_NAME = "std::_Sp_counted_base<(__gnu_cxx::_Lock_policy)2>"
    CONSTRUCTOR_NAME = CLASS_NAME + "::_Sp_counted_base()"
    ADD_REF_COPY_NAME = CLASS_NAME + "::_M_add_ref_copy()"
    ADD_REF_LOCK_NAME = CLASS_NAME + "::_M_add_ref_lock_nothrow()"
    RELEASE_NAME = CLASS_NAME + "::_M_release()"

    def __init__(self):
        self.address = gdb.parse_and_eval("this")
        self.use_count = 1
        self.backtraces = [Backtrace("init")]
        logging.debug("__init__(%s)", self.address)

    def add_ref_copy(self):
        logging.debug("add_ref_copy(%s)", self.address)
        self.backtraces.append(Backtrace("acquire"))

    def add_ref_lock(self):
        logging.debug("add_ref_lock(%s)", self.address)
        self.backtraces.append(Backtrace("acquire"))

    def release(self):
        logging.debug("release(%s)", self.address)
        self.backtraces.append(Backtrace("release"))
        self.use_count = SpCountedBase.__use_count()

    @staticmethod
    def __use_count():
        return int(gdb.parse_and_eval("_M_use_count"))

    def export(self):
        return {
            "address": str(self.address),
            "backtraces": list(map(lambda backtrace: backtrace.export(),
                                   self.backtraces))
        }


class Tracker:
    def __init__(self, report_file):
        # dict from str(_Sp_counted_base address) to usage data (SpCountedBase)
        self.__instances = {}
        # overall number of created instances
        self.__instances_created = 0
        if len(report_file) == 0:
            report_file = "tracked-shared-ptrs"
        self.__reportFile = os.path.abspath(report_file)

    def new(self):
        result = SpCountedBase()
        address_str = str(result.address)
        if address_str in self.__instances:
            raise RuntimeError(address_str + " already exists")
        self.__instances[address_str] = result
        self.__instances_created += 1
        return result

    def current_or_none(self):
        address = gdb.parse_and_eval("this")
        address_str = str(address)
        return self.__instances.get(address_str)

    def current(self):
        address = gdb.parse_and_eval("this")
        address_str = str(address)
        result = self.__instances.get(address_str)
        if result is None:
            raise RuntimeError(address_str + " does not exist")
        return result

    def release_current(self):
        current = self.current()
        current.release()
        if current.use_count == 1:
            del self.__instances[str(current.address)]

    def on_exit(self, event):
        result = {
            "success": len(self.__instances) == 0,
            "instances": list(map(lambda instance: instance.export(),
                                  self.__instances.values())),
            "instances-created": self.__instances_created
        }
        with open(self.__reportFile, "w") as f:
            json.dump(result, f, indent=4)
        logging.info("report written to " + self.__reportFile)
        gdb.post_event(gdb_quit)


class ConstructorBreakpoint(gdb.Breakpoint):
    def __init__(self, tracker):
        gdb.Breakpoint.__init__(self, SpCountedBase.CONSTRUCTOR_NAME)
        self.tracker = tracker

    def stop(self):
        self.tracker.new()
        gdb.post_event(gdb_continue)


class AddRefCopyBreakpoint(gdb.Breakpoint):
    def __init__(self, tracker):
        gdb.Breakpoint.__init__(self, SpCountedBase.ADD_REF_COPY_NAME)
        self.tracker = tracker

    def stop(self):
        self.tracker.current().add_ref_copy()
        gdb.post_event(gdb_continue)


class AddRefLockBreakpoint(gdb.Breakpoint):
    def __init__(self, tracker):
        gdb.Breakpoint.__init__(self, SpCountedBase.ADD_REF_LOCK_NAME)
        self.tracker = tracker

    def stop(self):
        current = self.tracker.current_or_none()
        if current is not None:
            current.add_ref_lock()
        gdb.post_event(gdb_continue)


class ReleaseBreakpoint(gdb.Breakpoint):
    def __init__(self, tracker):
        gdb.Breakpoint.__init__(self, SpCountedBase.RELEASE_NAME)
        self.tracker = tracker

    def stop(self):
        self.tracker.release_current()
        gdb.post_event(gdb_continue)


class PythonLogLevelCommand(gdb.Command):
    def __init__(self):
        gdb.Command.__init__(self, "python-log-level", gdb.COMMAND_USER)

    def invoke(self, argument, from_tty):
        logging.basicConfig(level=parse_log_level(argument))


class TrackSharedPtrsCommand(gdb.Command):
    def __init__(self):
        gdb.Command.__init__(self, "track-shared-ptrs", gdb.COMMAND_USER)

    def invoke(self, argument, from_tty):
        tracker = Tracker(argument)
        ConstructorBreakpoint(tracker)
        AddRefCopyBreakpoint(tracker)
        AddRefLockBreakpoint(tracker)
        ReleaseBreakpoint(tracker)
        gdb.events.exited.connect(tracker.on_exit)
        gdb_run()


PythonLogLevelCommand()
TrackSharedPtrsCommand()
