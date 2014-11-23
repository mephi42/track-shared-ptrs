#!/usr/bin/env python
import gdb
import json
import logging
import os
import re


def gdb_run():
    gdb.execute("run")


def gdb_continue():
    gdb.execute("continue")


def gdb_quit():
    gdb.execute("quit")


def gdb_breakpoint(spec, handler):
    class Breakpoint(gdb.Breakpoint):
        def __init__(self):
            gdb.Breakpoint.__init__(self, spec)

        def stop(self):
            handler()
            gdb.post_event(gdb_continue)

    return Breakpoint()


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
    SHARED_PTR_REGEX = re.compile("^std::__shared_ptr")
    ACQUIRE = "acquire"
    RELEASE = "release"

    def __init__(self, tpe):
        self.tpe = tpe
        self.lines = []
        self.shared_ptr_address_str = None
        self.shared_ptr_function_str = None
        frame = gdb.newest_frame()
        while frame is not None:
            function_str = str(frame.function())
            sal = frame.find_sal()
            if sal.symtab is None:
                location_str = "???"
            else:
                filename = sal.symtab.filename
                line = sal.line
                location_str = filename + ":" + str(line)
            self.lines.append(function_str + " at " + location_str)
            if self.shared_ptr_address_str is None:
                if Backtrace.SHARED_PTR_REGEX.match(function_str):
                    self.shared_ptr_address_str = str(frame.read_var("this"))
                    self.shared_ptr_function_str = function_str
            frame = frame.older()
        if self.shared_ptr_address_str is None:
            raise RuntimeError(
                "Cannot derive shared_ptr instance from backtrace\n" +
                str(self))

    def export(self):
        return {
            "type": self.tpe,
            "shared_ptr": {
                "address": self.shared_ptr_address_str,
                "function": self.shared_ptr_function_str
            },
            "lines": self.lines
        }

    def __str__(self):
        return json.dumps(self.export(), indent=4)


class SpCountedBase:
    CLASS_NAME = "std::_Sp_counted_base<(__gnu_cxx::_Lock_policy)2>"
    CONSTRUCTOR_NAME = CLASS_NAME + "::_Sp_counted_base()"
    ADD_REF_COPY_NAME = CLASS_NAME + "::_M_add_ref_copy()"
    ADD_REF_LOCK_NAME = CLASS_NAME + "::_M_add_ref_lock()"
    ADD_REF_LOCK_NOTHROW_NAME = CLASS_NAME + "::_M_add_ref_lock_nothrow()"
    RELEASE_NAME = CLASS_NAME + "::_M_release()"

    def __init__(self):
        self.address = gdb.parse_and_eval("this")
        self.use_count = 1
        self.backtraces = [Backtrace(Backtrace.ACQUIRE)]
        logging.debug("__init__(%s)", self.address)

    def add_ref_copy(self):
        logging.debug("add_ref_copy(%s)", self.address)
        self.backtraces.append(Backtrace(Backtrace.ACQUIRE))

    def add_ref_lock(self):
        logging.debug("add_ref_lock(%s)", self.address)
        self.backtraces.append(Backtrace(Backtrace.ACQUIRE))

    def release(self):
        logging.debug("release(%s)", self.address)
        backtrace = Backtrace(Backtrace.RELEASE)
        if not self.__annihilate_backtrace(backtrace):
            self.backtraces.append(backtrace)
        self.use_count = SpCountedBase.__use_count()

    def __annihilate_backtrace(self, backtrace):
        needle = backtrace.shared_ptr_address_str
        i = len(self.backtraces) - 1
        while i >= 0:
            if (self.backtraces[i].shared_ptr_address_str == needle and
                    self.backtraces[i].tpe == Backtrace.ACQUIRE):
                del self.backtraces[i]
                return True
            i -= 1
        return False

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

    def add_ref_copy_current(self):
        self.current().add_ref_copy()

    def add_ref_lock_current(self):
        current = self.current_or_none()
        if current is not None:
            current.add_ref_lock()

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


class PythonLogLevelCommand(gdb.Command):
    def __init__(self):
        gdb.Command.__init__(self, "python-log-level", gdb.COMMAND_NONE)

    def invoke(self, argument, from_tty):
        logging.basicConfig(level=parse_log_level(argument))


class TrackSharedPtrsCommand(gdb.Command):
    def __init__(self):
        gdb.Command.__init__(self, "track-shared-ptrs", gdb.COMMAND_NONE)

    def invoke(self, argument, from_tty):
        tracker = Tracker(argument)
        gdb_breakpoint(SpCountedBase.CONSTRUCTOR_NAME,
                       tracker.new)
        gdb_breakpoint(SpCountedBase.ADD_REF_COPY_NAME,
                       tracker.add_ref_copy_current)
        gdb_breakpoint(SpCountedBase.ADD_REF_LOCK_NAME,
                       tracker.add_ref_lock_current)
        gdb_breakpoint(SpCountedBase.ADD_REF_LOCK_NOTHROW_NAME,
                       tracker.add_ref_lock_current)
        gdb_breakpoint(SpCountedBase.RELEASE_NAME,
                       tracker.release_current)
        gdb.events.exited.connect(tracker.on_exit)
        gdb_run()


PythonLogLevelCommand()
TrackSharedPtrsCommand()
