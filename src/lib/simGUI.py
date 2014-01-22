#!/usr/bin/env python
# -*- coding: utf-8 -*-
# generated by wxGlade 0.6.3 on Sun Jan 31 10:48:54 2010

"""
    ==================================
    simGUI.py - Experiment Monitor GUI
    ==================================

    A basic user interface for watching the state of the robot during simulation/experiment,
    and pausing/resuming execution.
"""

import math, time, sys, os, re
import wxversion
import wx, wx.richtext, wx.grid
import threading
import project, mapRenderer, regions
import socket
import copy
import xmlrpclib
from SimpleXMLRPCServer import SimpleXMLRPCServer
import random

# begin wxGlade: extracode
# end wxGlade

class SimGUI_Frame(wx.Frame):
    def __init__(self, *args, **kwds):
        # begin wxGlade: SimGUI_Frame.__init__
        kwds["style"] = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
        self.window_1 = wx.SplitterWindow(self, -1, style=wx.SP_3D|wx.SP_BORDER|wx.SP_LIVE_UPDATE)
        self.window_1_pane_2 = wx.Panel(self.window_1, -1)
        self.notebook_1 = wx.Notebook(self.window_1_pane_2, -1, style=0)
        self.notebook_1_pane_2 = wx.Panel(self.notebook_1, -1)
        self.notebook_1_pane_1 = wx.Panel(self.notebook_1, -1)
        self.window_1_pane_1 = wx.Panel(self.window_1, -1)
        self.text_ctrl_sim_log = wx.richtext.RichTextCtrl(self.notebook_1_pane_1, -1, "", style=wx.TE_MULTILINE|wx.TE_READONLY)
        self.text_ctrl_slurpout = wx.richtext.RichTextCtrl(self.notebook_1_pane_2, -1, "", style=wx.TE_MULTILINE|wx.TE_READONLY)
        self.text_ctrl_slurpin = wx.TextCtrl(self.notebook_1_pane_2, -1, "", style=wx.TE_PROCESS_ENTER)
        self.button_SLURPsubmit = wx.Button(self.notebook_1_pane_2, -1, "Submit")
        self.button_sim_startPause = wx.Button(self.window_1_pane_2, -1, "Start")
        self.button_sim_log_clear = wx.Button(self.window_1_pane_2, -1, "Clear Log")
        self.button_sim_log_export = wx.Button(self.window_1_pane_2, -1, "Export Log...")
        self.label_1 = wx.StaticText(self.window_1_pane_2, -1, "Show log messages for:")
        self.checkbox_statusLog_targetRegion = wx.CheckBox(self.window_1_pane_2, -1, "Target region announcements")
        self.checkbox_statusLog_propChange = wx.CheckBox(self.window_1_pane_2, -1, "System proposition changes")
        self.checkbox_statusLog_border = wx.CheckBox(self.window_1_pane_2, -1, "Region border crossings")
        self.checkbox_statusLog_other = wx.CheckBox(self.window_1_pane_2, -1, "Other debugging messages")

        self.__set_properties()
        self.__do_layout()

        self.Bind(wx.EVT_TEXT_ENTER, self.onSLURPSubmit, self.text_ctrl_slurpin)
        self.Bind(wx.EVT_BUTTON, self.onSLURPSubmit, self.button_SLURPsubmit)
        self.Bind(wx.EVT_BUTTON, self.onSimStartPause, self.button_sim_startPause)
        self.Bind(wx.EVT_BUTTON, self.onSimClear, self.button_sim_log_clear)
        self.Bind(wx.EVT_BUTTON, self.onSimExport, self.button_sim_log_export)
        self.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self.onResize, self.window_1)
        # end wxGlade
        self.window_1_pane_1.SetBackgroundStyle(wx.BG_STYLE_CUSTOM)
        self.mapBitmap = None

        self.window_1_pane_1.Bind(wx.EVT_PAINT, self.onPaint)
        self.Bind(wx.EVT_ERASE_BACKGROUND, self.onEraseBG)

        self.proj = project.Project()
        self.proj.setSilent(True)

        # Make status bar at bottom.

        self.sb = wx.StatusBar(self)
        self.SetStatusBar(self.sb)
        self.sb.SetFieldsCount(1)
        self.sb.SetStatusText("PAUSED")

        self.button_sim_log_export.Enable(False)

        # Connect to executor
        try:
            executor_port = int(sys.argv[1])
        except ValueError:
            print "ERROR: Invalid port '{}'".format(arg)
            sys.exit(2)

        self.executorProxy = xmlrpclib.ServerProxy("http://127.0.0.1:{}".format(executor_port), allow_none=True)

        # Create the XML-RPC server
        # Search for a port we can successfully bind to
        while True:
            listen_port = random.randint(10000, 65535)
            try:
                self.xmlrpc_server = SimpleXMLRPCServer(("127.0.0.1", listen_port), logRequests=False, allow_none=True)
            except socket.error as e:
                pass
            else:
                break

        # Register functions with the XML-RPC server
        self.xmlrpc_server.register_function(self.handleEvent)

        # Kick off the XML-RPC server thread    
        self.XMLRPCServerThread = threading.Thread(target=self.xmlrpc_server.serve_forever)
        self.XMLRPCServerThread.daemon = True
        self.XMLRPCServerThread.start()
        print "SimGUI listening for XML-RPC calls on http://127.0.0.1:{} ...".format(listen_port)

        # Register with executor for event callbacks   
        self.executorProxy.registerExternalEventTarget("http://127.0.0.1:{}".format(listen_port))
 
        self.robotPos = None
        self.robotVel = (0,0)

        self.markerPos = None

        self.dialogueManager = None
        self.currentGoal = None

        self.Bind(wx.EVT_CLOSE, self.onClose)
        
        #################### ENV ASSUMPTION LEARNING ##################
        self.currentColor = "BLACK"
        ################################################################

    def loadRegionFile(self, filename):
        self.proj.rfi = regions.RegionFileInterface()
        self.proj.rfi.readFile(filename)

        self.Bind(wx.EVT_SIZE, self.onResize, self)
        self.onResize()

    def loadSpecFile(self, filename):
        self.proj.loadProject(filename)

        self.Bind(wx.EVT_SIZE, self.onResize, self)

        if self.proj.compile_options["parser"] == "slurp":
            self.initDialogue()
        else:
            self.notebook_1.DeletePage(1)

        self.onResize()

    def handleEvent(self, eventType, eventData):
        """
        Processes messages from the controller, and updates the GUI accordingly
        """

        # Update stuff (should put these in rough order of frequency for optimal speed
        if eventType == "FREQ":
            wx.CallAfter(self.sb.SetStatusText, "Running at approximately {}Hz...".format(eventData), 0)
        elif eventType == "POSE":
            self.robotPos = eventData
            wx.CallAfter(self.onPaint)
        elif eventType == "MARKER":
            self.markerPos = eventData
            wx.CallAfter(self.onPaint)
        elif eventType == "VEL":
            # We can't plot anything before we have a map
            if self.mapBitmap is None:
                print "Received drawing command before map.  You probably have an old execute.py process running; please kill it and try again."
                return
            [x,y] = eventData
            [x,y] = map(int, (self.mapScale*x, self.mapScale*y)) 
            self.robotVel = (x, y)
        elif eventType == "PAUSE":
            wx.CallAfter(self.sb.SetStatusText, "PAUSED.", 0)
        elif eventType == "SPEC":
            wx.CallAfter(self.loadSpecFile, eventData)
        elif eventType == "REGIONS":
            wx.CallAfter(self.loadRegionFile, eventData)
        elif eventData.startswith("Output proposition"):
            if self.checkbox_statusLog_propChange.GetValue():
                wx.CallAfter(self.appendLog, eventData + "\n", color="GREEN") 
        elif eventData.startswith("Heading to"):
            if self.checkbox_statusLog_targetRegion.GetValue():
                wx.CallAfter(self.appendLog, eventData + "\n", color="BLUE") 
        elif eventData.startswith("Crossed border"):
            if self.checkbox_statusLog_border.GetValue():
                wx.CallAfter(self.appendLog, eventData + "\n", color="CYAN") 
        #################### ENV ASSUMPTION LEARNING ##################
        elif eventType == "VIOLATION":
            wx.CallAfter(self.appendLog, eventData + "\n", color="RED") 
            self.currentColor = "RED"
        elif eventType == "RESOLVED":
            wx.CallAfter(self.appendLog, eventData + "\n", color="GREEN") 
            self.currentColor = "BLACK"
        elif eventType == "INFO":
            wx.CallAfter(self.appendLog, eventData + "\n", color= self.currentColor) 
        ###############################################################
        else:
            # Detect our current goal index
            if eventData.startswith("Currently pursuing goal"):
                m = re.search(r"#(\d+)", eventData)
                if m is not None:
                    self.currentGoal = int(m.group(1))

            if self.checkbox_statusLog_other.GetValue():
                if eventData != "":
                    wx.CallAfter(self.appendLog, eventData + "\n", color="BLACK") 

    def __set_properties(self):
        # begin wxGlade: SimGUI_Frame.__set_properties
        self.SetTitle("Simulation Status")
        self.SetSize((836, 713))
        self.button_SLURPsubmit.SetDefault()
        self.checkbox_statusLog_targetRegion.SetValue(1)
        self.checkbox_statusLog_propChange.SetValue(1)
        self.checkbox_statusLog_border.SetValue(1)
        self.checkbox_statusLog_other.SetValue(1)
        # end wxGlade

    def __do_layout(self):
        # begin wxGlade: SimGUI_Frame.__do_layout
        sizer_1 = wx.BoxSizer(wx.VERTICAL)
        sizer_2 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_5 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_43_copy_1 = wx.BoxSizer(wx.VERTICAL)
        sizer_3 = wx.BoxSizer(wx.VERTICAL)
        sizer_43_copy_copy = wx.BoxSizer(wx.VERTICAL)
        sizer_6 = wx.BoxSizer(wx.VERTICAL)
        sizer_7 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_4 = wx.BoxSizer(wx.HORIZONTAL)
        sizer_5.Add((5, 30), 0, 0, 0)
        sizer_43_copy_copy.Add((20, 5), 0, 0, 0)
        sizer_4.Add(self.text_ctrl_sim_log, 1, wx.ALL|wx.EXPAND, 5)
        self.notebook_1_pane_1.SetSizer(sizer_4)
        sizer_6.Add(self.text_ctrl_slurpout, 1, wx.ALL|wx.EXPAND, 5)
        sizer_7.Add(self.text_ctrl_slurpin, 1, wx.ALL|wx.EXPAND, 5)
        sizer_7.Add(self.button_SLURPsubmit, 0, wx.ALL, 5)
        sizer_6.Add(sizer_7, 0, wx.EXPAND, 0)
        self.notebook_1_pane_2.SetSizer(sizer_6)
        self.notebook_1.AddPage(self.notebook_1_pane_1, "Status Log")
        self.notebook_1.AddPage(self.notebook_1_pane_2, "SLURP Dialogue")
        sizer_43_copy_copy.Add(self.notebook_1, 1, wx.EXPAND, 0)
        sizer_43_copy_copy.Add((20, 5), 0, 0, 0)
        sizer_5.Add(sizer_43_copy_copy, 6, wx.EXPAND, 0)
        sizer_5.Add((20, 30), 0, 0, 0)
        sizer_43_copy_1.Add((20, 20), 0, 0, 0)
        sizer_43_copy_1.Add(self.button_sim_startPause, 0, wx.LEFT|wx.RIGHT|wx.EXPAND|wx.ALIGN_CENTER_HORIZONTAL, 20)
        sizer_43_copy_1.Add((20, 10), 0, 0, 0)
        sizer_43_copy_1.Add(self.button_sim_log_clear, 0, wx.LEFT|wx.RIGHT|wx.EXPAND|wx.ALIGN_CENTER_HORIZONTAL, 20)
        sizer_43_copy_1.Add((20, 10), 0, 0, 0)
        sizer_43_copy_1.Add(self.button_sim_log_export, 0, wx.LEFT|wx.RIGHT|wx.EXPAND|wx.ALIGN_CENTER_HORIZONTAL, 20)
        sizer_43_copy_1.Add((20, 10), 0, 0, 0)
        sizer_3.Add((20, 20), 0, 0, 0)
        sizer_3.Add(self.label_1, 0, 0, 0)
        sizer_3.Add(self.checkbox_statusLog_targetRegion, 0, wx.TOP|wx.BOTTOM, 5)
        sizer_3.Add(self.checkbox_statusLog_propChange, 0, wx.TOP|wx.BOTTOM, 5)
        sizer_3.Add(self.checkbox_statusLog_border, 0, wx.TOP|wx.BOTTOM, 5)
        sizer_3.Add(self.checkbox_statusLog_other, 0, wx.TOP|wx.BOTTOM, 5)
        sizer_43_copy_1.Add(sizer_3, 1, wx.EXPAND, 0)
        sizer_5.Add(sizer_43_copy_1, 3, wx.EXPAND, 0)
        sizer_5.Add((20, 30), 0, 0, 0)
        self.window_1_pane_2.SetSizer(sizer_5)
        self.window_1.SplitHorizontally(self.window_1_pane_1, self.window_1_pane_2)
        sizer_2.Add(self.window_1, 1, wx.EXPAND, 0)
        sizer_2.Add((20, 20), 0, 0, 0)
        sizer_1.Add(sizer_2, 1, wx.EXPAND, 0)
        self.SetSizer(sizer_1)
        self.Layout()
        # end wxGlade

        self.window_1.SetSashPosition(self.GetSize().y/2)
        self.window_1_pane_1.SetBackgroundColour(wx.WHITE)   

    def onResize(self, event=None): # wxGlade: SimGUI_Frame.<event_handler>
        size = self.window_1_pane_1.GetSize()
        self.mapBitmap = wx.EmptyBitmap(size.x, size.y)
        self.mapScale = mapRenderer.drawMap(self.mapBitmap, self.proj.rfi, scaleToFit=True, drawLabels=mapRenderer.LABELS_ALL_EXCEPT_OBSTACLES, memory=True)

        self.Refresh()
        self.Update()

        if event is not None:
            event.Skip()

    def onEraseBG(self, event):
        # Avoid unnecessary flicker by intercepting this event
        pass

    def onPaint(self, event=None):
        if self.mapBitmap is None:
            return

        if event is None:
            dc = wx.ClientDC(self.window_1_pane_1)
        else:
            pdc = wx.AutoBufferedPaintDC(self.window_1_pane_1)
            try:
                dc = wx.GCDC(pdc)
            except:
                dc = pdc

        dc.BeginDrawing()

        # Draw background
        dc.DrawBitmap(self.mapBitmap, 0, 0)

        # Draw robot
        if self.robotPos is not None:
            [x,y] = map(lambda x: int(self.mapScale*x), self.robotPos) 
            dc.DrawCircle(x, y, 5)
        if self.markerPos is not None:
            [m,n] = map(lambda m: int(self.mapScale*m), self.markerPos) 
            dc.SetBrush(wx.Brush(wx.RED))
            dc.DrawCircle(m, n, 5)

        # Draw velocity vector of robot (for debugging)
        #dc.DrawLine(self.robotPos[0], self.robotPos[1], 
        #            self.robotPos[0] + self.robotVel[0], self.robotPos[1] + self.robotVel[1])

        dc.EndDrawing()
        
        if event is not None:
            event.Skip()

    def appendLog(self, text, color="BLACK"):
        # for printing everything on the log
            
        # annotate any pXXX region names with their human-friendly name
        # convert to set to avoid infinite explosion
        for p_reg in set(re.findall(r'\b(p\d+)\b',text)):
            for rname, subregs in self.proj.regionMapping.iteritems():
                if p_reg in subregs:
                    break
            text = re.sub(r'\b'+p_reg+r'\b', '%s (%s)' % (p_reg, rname), text)

        self.text_ctrl_sim_log.SetInsertionPointEnd()
        self.text_ctrl_sim_log.BeginTextColour(color)
        self.text_ctrl_sim_log.WriteText("["+time.strftime("%H:%M:%S")+"] "+text)
        self.text_ctrl_sim_log.EndTextColour()
        self.text_ctrl_sim_log.ShowPosition(self.text_ctrl_sim_log.GetLastPosition())
        self.text_ctrl_sim_log.Refresh()

    def onSimStartPause(self, event): # wxGlade: SimGUI_Frame.<event_handler>
        btn_label = self.button_sim_startPause.GetLabel()
        if btn_label == "Start" or btn_label == "Resume":
            self.button_sim_log_export.Enable(False)
            self.executorProxy.resume()
            self.appendLog("%s!\n" % btn_label,'GREEN')
            self.button_sim_startPause.SetLabel("Pause")
        else:
            self.executorProxy.pause()
            self.appendLog('Pause...\n','RED')
            self.button_sim_log_export.Enable(True)
            self.button_sim_startPause.SetLabel("Resume")

        self.Refresh()
        event.Skip()

    def onSimExport(self, event): # wxGlade: SimGUI_Frame.<event_handler>
        """
        Ask the user for a filename to save the Log as, and then save it.
        """
        default = 'StatusLog'
    
        # Get a filename
        fileName = wx.FileSelector("Save File As", 
                                    os.path.join(os.getcwd(),'examples'),
                                    default_filename=default,
                                    default_extension="txt",
                                    wildcard="Status Log files (*.txt)|*.txt",
                                    flags = wx.SAVE | wx.OVERWRITE_PROMPT)
        if fileName == "": return # User cancelled.

        # Force a .txt extension.  How mean!!!
        if os.path.splitext(fileName)[1] != ".txt":
            fileName = fileName + ".txt"
        

        # Save data to the file
        self.saveFile(fileName)
        event.Skip()

    def saveFile(self, fileName):
        """
        Write all data out to a file.
        """

        if fileName is None:
            return

        f = open(fileName,'w')

        print >>f, "Experiment Status Log"
        print >>f
        # write the log
        print >>f, str(self.text_ctrl_sim_log.GetValue())

        f.close()

    def onClose(self, event):
        try:
            self.executorProxy.shutdown()
        except socket.error:
            # Executor probably crashed
            pass

        self.xmlrpc_server.shutdown()
        self.XMLRPCServerThread.join()
        #time.sleep(2)
        event.Skip()

    def onSimClear(self, event): # wxGlade: SimGUI_Frame.<event_handler>
        self.text_ctrl_sim_log.Clear()
        event.Skip()

    def initDialogue(self):
        # Add SLURP to path for import
        p = os.path.dirname(os.path.abspath(__file__))
        sys.path.append(os.path.join(p, "..", "etc", "SLURP"))
        from ltlbroom.specgeneration import SpecGenerator
        _SLURP_SPEC_GENERATOR = SpecGenerator()
    
        # Filter out regions it shouldn't know about
        filtered_regions = [region.name for region in self.proj.rfi.regions 
                            if not (region.isObstacle or region.name.lower() == "boundary")]

        sensorList = copy.deepcopy(self.proj.enabled_sensors)
        robotPropList = self.proj.enabled_actuators + self.proj.all_customs
        
        text = self.proj.specText

        LTLspec_env, LTLspec_sys, self.proj.internal_props, internal_sensors, results, responses, traceback = \
            _SLURP_SPEC_GENERATOR.generate(text, sensorList, filtered_regions, robotPropList,
                                           self.proj.currentConfig.region_tags)

        from ltlbroom.dialog import DialogManager
        self.dialogueManager = DialogManager(traceback)

    def onSLURPSubmit(self, event): # wxGlade: SimGUI_Frame.<event_handler>
        if self.text_ctrl_slurpin.GetValue() == "":
            event.Skip()
            return
        
        user_text = self.text_ctrl_slurpin.GetValue()

        # echo
        self.text_ctrl_slurpout.BeginBold()
        self.text_ctrl_slurpout.AppendText("User: ")
        self.text_ctrl_slurpout.EndBold()
        self.text_ctrl_slurpout.AppendText(user_text + "\n")

        self.text_ctrl_slurpout.ShowPosition(self.text_ctrl_slurpout.GetLastPosition())
        self.text_ctrl_slurpout.Refresh()

        self.text_ctrl_slurpin.Clear()

        # response
        if self.dialogueManager is None:
            self.text_ctrl_slurpout.BeginBold()
            self.text_ctrl_slurpout.AppendText("Error: Dialogue Manager not initialized")
            self.text_ctrl_slurpout.EndBold()
        else:
            sys_text = self.dialogueManager.tell(user_text, self.currentGoal)
            self.text_ctrl_slurpout.BeginBold()
            self.text_ctrl_slurpout.AppendText("System: ")
            self.text_ctrl_slurpout.EndBold()
            self.text_ctrl_slurpout.AppendText(sys_text + "\n")

        self.text_ctrl_slurpout.ShowPosition(self.text_ctrl_slurpout.GetLastPosition())
        self.text_ctrl_slurpout.Refresh()

        event.Skip()

# end of class SimGUI_Frame




if __name__ == "__main__":
    app = wx.PySimpleApp(0)
    wx.InitAllImageHandlers()
    simGUI_Frame = SimGUI_Frame(None, -1, "")
    app.SetTopWindow(simGUI_Frame)
    simGUI_Frame.Show()
    app.MainLoop()
