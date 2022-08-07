from typing import ByteString
import win32com.client
import os, sys
import winreg
import time
import math
import struct
from shutil import copyfile
from ctypes import *

class Metadata:
    def int32(self, x):
        pad = "0x"
        count = 1
        while True:
            if len(pad) == len(hex(x)):
                break
            pad += "F"
            count += 1
        con_hex = int(pad, 16)
        return -(con_hex+1 - x)

    def cluster_size(self, param):
        cluster = param * self.structure["ClusterSize"]
        return cluster
    
    def convert_byte(self, param):
        return int(param[2:], 16)
    
    def byte_beautifier(self, start, size):
        self.drive.seek(start)
        buf = self.drive.read(size)
        for i in range(math.ceil(size/16)):
            v = i * 16
            result = ""
            for j in range(v+0, v+16):
                if j == v+8:
                    result += "  "
                buf_regex = hex(buf[j]).upper().replace("0X", "")
                if len(buf_regex) == 1:
                    buf_regex = "0" + buf_regex
                result += buf_regex + " "
            print(result)

    def convert_ascii(self, string):
        ret = ""
        for s in string:
            ret += str(hex(ord(s)).replace("0x", "")).upper() + "00"
        return ret

    def entryOffset(self, param):
        eoffset = self.structure["MFToffset"] + param * 1024
        return eoffset

    def open_windows_partition(self,letter,mode="rb", buffering=-1, encoding=None, errors=None, newline=None, closefd=True, opener=None):
        return open(fr"\\.\{letter}:", mode, buffering, encoding, errors, newline, closefd, opener)

    def queryExtents(self):
        try:
            dataRuns = os.popen("fsutil file queryExtents \"{0}\"".format(self.filename)).read()
        except:
            print("[FAIL] queryExtents Failed..")
            quit()
        if dataRuns.find("액세스") != -1 or dataRuns.find("Access") != -1:
            print("[FAIL] access is denied")
            print("[+] manually data runs parse start..")
            return self.manually_dataruns()
        if dataRuns.find("파일") != -1 or dataRuns.find("cannot find") != -1:
            print("[FAIL] file not found..")
            quit()
        if dataRuns.find("범위") != -1 or dataRuns.find("range") != -1:
            print("[FAIL] $DATA attribute Resident File..")
            quit()
        length = list()
        offset = list()
        for runlist in dataRuns.split("\n"):
            if runlist == "":
                continue
            length.append(self.convert_byte(runlist.split(":")[2].split("LCN")[0].strip()))
            offset.append(self.convert_byte(runlist.split(":")[3].split("VCN")[0].strip()))
        return length, offset
    
    def manually_dataruns(self):
        wFileName = self.filename.split("\\")[-1]
        entryindex = self.mftEntry[wFileName.upper()]
        self.drive.seek(self.entryOffset(entryindex))
        readEntry = self.drive.read(1024)

        idx = 0
        for b in readEntry:
            if idx%16 == 0 or idx%8 == 0:
                if b == 128:
                    break
            idx += 1
        dataRunStartFlag = struct.unpack('<L', readEntry[idx + 32:idx + 34] + b"\x00\x00")[0]
        endFlag = 0
        runlist = list()
        for dr in readEntry[idx+dataRunStartFlag:]:
            if dr == 255:
                if readEntry[idx+dataRunStartFlag+endFlag+1] == 255:
                    break
            runlist.append(dr)
            endFlag += 1
        
        offsetList = [0]
        idx = 0
        nextOffset = 0
        for rl in runlist:
            if nextOffset == idx:
                try:
                    nextOffset = int(hex(rl)[2]) + int(hex(rl)[3]) + idx + 1
                except IndexError:
                    break
                if runlist[nextOffset] == 0:
                    break
                offsetList.append(nextOffset)
            idx += 1
        
        vlength = list()
        voffset = list()
        idx = 0
        for ol in offsetList:
            drunLenth = int(hex(runlist[ol])[3])
            drunOffset = int(hex(runlist[ol])[2])
            buf1 = bytes()
            for dlen in range(drunLenth):
                dlen = dlen + 1 + ol
                buf_regex = hex(runlist[dlen]).upper().replace("0X", "")
                if len(buf_regex) == 1:
                    buf_regex = "0" + buf_regex
                else:
                    buf_regex = "" + buf_regex
                buf1 += bytes.fromhex(buf_regex)
            vlength.append(struct.unpack('<L', buf1 + b"\x00"*(4-len(buf1)))[0])

            buf2 = bytes()
            for dof in range(drunOffset):
                dof = dof + 1 + ol + drunLenth
                buf_regex = hex(runlist[dof]).upper().replace("0X", "")
                if len(buf_regex) == 1:
                    buf_regex = "0" + buf_regex
                else:
                    buf_regex = "" + buf_regex
                buf2 += bytes.fromhex(buf_regex)
            voffset.append(struct.unpack('<L', buf2 + b"\x00"*(4-len(buf2)))[0])
        
        for vl in voffset:
            negativeCheck = hex(vl).replace("0x", "")
            buf = ""
            if len(negativeCheck)%2 == 0:
                buf = "" + negativeCheck
            else:
                buf = "0" + negativeCheck
            
            if int(buf[0], 16) > 7:
                print(self.int32(vl))

        print(voffset)
        print(vlength)

    def cluster_parse(self):
        length, offset = self.queryExtents()
        idx = len(length)
        wFileName = self.filename.split("\\")[-1].replace(":","_")
        fileSize = 0
        with open(wFileName, "wb") as f:
            for i in range(idx):
                if hex(offset[i]).upper().find("0XFFFFFF") != -1:
                    print("[{0}] Sparse Area  Length : {1}".format(i, hex(self.cluster_size(length[i]))))
                    continue
                else:
                    print("[{0}] Start Offset : {1}  End Offset : {3}  Length : {2}".format(i, hex(self.cluster_size(offset[i])), hex(self.cluster_size(length[i])), hex(self.cluster_size(offset[i]+length[i]))))
                    self.drive.seek(0)
                    self.drive.seek(self.cluster_size(offset[i]))
                    f.write(self.drive.read(self.cluster_size(length[i])))
                    fileSize += self.cluster_size(length[i])
                
        print("[DONE] File Size : {0} bytes".format(fileSize))
    
    def __vbr_structure(self):
        self.drive.seek(0)
        vbrSector = self.drive.read(512)
        ntfsCheck = vbrSector[3:7].decode('ascii')
        if ntfsCheck != "NTFS":
            print("[FAIL] this is not a NTFS system.")
            quit()
        bps = struct.unpack('<L', vbrSector[11:13] + b"\x00\x00")[0]
        spc = struct.unpack('<L', vbrSector[13:14] + b"\x00\x00\x00")[0]
        csize = bps * spc
        moffset = struct.unpack('<L', vbrSector[48:52])[0] * csize
        self.structure = {
            "BPS": bps,
            "SPC": spc,
            "ClusterSize": csize,
            "MFToffset": moffset
        }
        print(self.structure)
        
    def __init__(self):
        self.mftEntry = {
            "$MFT": 0,
            "$MFTMirr": 1,
            "$LOGFILE": 2,
            "$VOLUME": 3,
            "$ATTRDEF": 4,
            ".": 5,
            "$BITMAP": 6,
            "$BOOT": 7,
            "$BADCLUS": 8,
            "$SECURE": 9,
            "$UPCASE": 10,
            "$EXTEND": 11,
        }

        self.mftEntryHeader = 48
        self.mftFixup = 8
        self.mftFlag = 5

        drive = os.popen("echo %systemdrive%").read().strip()[0]
        self.drive = self.open_windows_partition(drive)
        self.filename = ""
        self.__vbr_structure()

    
    
class VSS:
    def hiveList(self):
        try:
            roothandle = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
            key = winreg.OpenKey(roothandle, "SYSTEM\\CurrentControlSet\\Control\\hivelist", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            info = winreg.QueryInfoKey(key)

        except Exception as e:
            return []

        resultPath = list()
        resultName = list()
        for i in range(info[1]):
            try:
                searchReg = winreg.EnumValue(key, i)[1]
                resultName.append(winreg.EnumValue(key, i)[0])
                convertPath = searchReg.split("\\")[3:]
                convertPath = '\\'.join(convertPath)
                resultPath.append(convertPath)
            except Exception as e:
                continue
        try:
            winreg.CloseKey(key)
        except Exception as e:
            pass
        return resultPath, resultName

    def vssList(self):
        wcd=win32com.client.Dispatch("WbemScripting.SWbemLocator")
        wmi=wcd.ConnectServer(".","root\cimv2")
        obj=wmi.ExecQuery("SELECT * FROM win32_ShadowCopy")
        return [x.DeviceObject for x in obj]
    
    def vssCreate(self, drive):
        wmi=win32com.client.GetObject("winmgmts:\\\\.\\root\cimv2:Win32_ShadowCopy")
        createmethod = wmi.Methods_("Create")
        createparams = createmethod.InParameters
        createparams.Properties_[1].value="{0}\\".format(drive)
        results = wmi.ExecMethod_("Create",createparams)
        return results.Properties_[1].value
    
    def copyFile(self, tp, en):
        if en.find("-") != -1:
            expName = en.split("\\")[-1] + "_"
        else:
            expName = ""
        fileName = expName + tp.split("\\")[-1]
        vscPath = tp
        list = self.vssList()
        w = open(fileName, "wb")
        try:
            with open('{0}\\{1}'.format(list[0], vscPath), "rb") as f:
                w.write(f.read())
            print("[DONE] \"{0}\" copy done.. ({1}\\{0})".format(fileName, os.getcwd()))
        except PermissionError:
            print("[FAIL] \"{0}\" cannot access..".format(fileName))
            w.close()
            os.system("del {0}".format(fileName))
        except FileNotFoundError:
            print("[FAIL] \"{0}\" file not found..".format(fileName))
            w.close()
            os.system("del {0}".format(fileName))
        w.close()
    
    def __init__(self):
        targetFile, exportName = self.hiveList()
        folder_name = "RegHive_" + time.strftime('%y%m%d%H%M%S')
        if not (os.path.isdir(folder_name)):
            os.makedirs(os.path.join(folder_name))
        try:
            os.chdir(folder_name)
        except:
            print("excute path change failed..")
            quit()
        drive = os.popen("echo %systemdrive%").read().strip()
        self.vssCreate(drive)
        for idx in range(len(targetFile)):
            if targetFile[idx] == "":
                continue
            self.copyFile(targetFile[idx], exportName[idx])

if __name__ == "__main__":
    if windll.shell32.IsUserAnAdmin() == False:
        print("Administrator privileges required.")
        quit()
    else:
        usage = "Usage \n\
                [1] getting Metadata : technote.py -M [FILE_NAME]\n\
                [2] getting Registry : technote.py -R\n\
                    "
        try:
            selectClass = sys.argv[1]
        except:
            print(usage)
            quit()
        if selectClass.upper() == "-M" or selectClass.upper() == "-R":
            if selectClass.upper() == "-M":
                try:
                    filename = sys.argv[2]
                except:
                    print(usage)
                    quit()
                runMetadata = Metadata()
                runMetadata.filename = filename
                runMetadata.manually_dataruns()
            else:
                runVSS = VSS()
        else:
            print(usage)
        