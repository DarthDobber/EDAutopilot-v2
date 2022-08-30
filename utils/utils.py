from multiprocessing import Process,Queue,shared_memory
import pyautogui
import keyboard
import psutil
import os
import win32gui
import win32file
import pathlib
import cv2
import re
import time
import numpy as np
import traceback
from utils.journal import *
from utils.keybinds import *
from utils.status import *
import pytesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'

## Constants
ALIGN_TRIMM_DELAY = 0.10
ALIGN_KEY_DELAY = 0.180
KEY_DEFAULT_DELAY = 0.120
KEY_REPEAT_DELAY = 0.200
MOUSE_CLICK_DELAY = 0.200
DELAY_BETWEEN_KEYS = 1.5
ALIGN_DEAD_ZONE = 0.6
ROLL_YAW_DEAD_ZONE = 10
TEMPLATE_CIRCLE_DEAD_ZONE = 52

globalWindowName = "Elite - Dangerous (CLIENT)"
globalProcessName = "EliteDangerous64.exe"
fileRootPath = pathlib.Path.cwd()

def joinPath(pathName):
    if '.vscode' in str(fileRootPath): root = fileRootPath.parent
    else: root = fileRootPath
    if pathName[0] == '/' or pathName[0] == '\\': pathName = pathName[1:]
    result = str(root.joinpath(pathName))
    return result

## In-Game Utils

def getSunPercent(outsideImage):
    return # WIP

def sendHexKey(keysDict, key, hold=None, repeat=1, repeat_delay=None, state=None):
    global KEY_DEFAULT_DELAY, KEY_REPEAT_DELAY
    if key is None:
        # print('Send an empty key')
        raise
    for i in range(repeat):
        if state is None or state == 1:
            PressKey(keysDict[key])
        if state is None:
            if hold:
                time.sleep(hold)
            else:
                time.sleep(KEY_DEFAULT_DELAY)
        if state is None or state == 0:
            ReleaseKey(keysDict[key])
        if repeat_delay:
            time.sleep(repeat_delay)
        elif repeat>2:
            time.sleep(KEY_REPEAT_DELAY)
        else:
            time.sleep(0.08)

def checkAlignWithTemplate(centerImg,circleImg): 
    result = False
    _,binary = cv2.threshold(centerImg,110,255,cv2.THRESH_BINARY)
    # result = cv2.matchTemplate(binary, circleImg, cv2.TM_CCORR)
    dst = cv2.matchTemplate(binary, circleImg, cv2.TM_CCOEFF)
    _, max_val, _, max_loc = cv2.minMaxLoc(dst)
    th,tw = circleImg.shape[:2]
    ch,cw = centerImg.shape[:2]
    if max_val > 10000000: # I dont know why
        tl = max_loc
        br = (tl[0] + tw, tl[1] + th)
        cirCenter = ((tl[0]+br[0])/2)*0.8,(tl[1]+br[1])/2 # template circle's center
        center = cw/2, ch/2
        result = abs(center[0]-cirCenter[0])<TEMPLATE_CIRCLE_DEAD_ZONE and abs(center[1]-cirCenter[1])<TEMPLATE_CIRCLE_DEAD_ZONE
    return result

def loadImage(img, grayscale=None):
    # load images if given filename, or convert as needed to opencv
    # Alpha layer just causes failures at this point, so flatten to RGB.
    # to matchTemplate, need template and image to be the same wrt having alpha

    if isinstance(img, str):
        # The function imread loads an image from the specified file and
        # returns it. If the image cannot be read (because of missing
        # file, improper permissions, unsupported or invalid format),
        # the function returns an empty matrix
        # http://docs.opencv.org/3.0-beta/modules/imgcodecs/doc/reading_and_writing_images.html
        if grayscale:
            img_cv = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
        else:
            img_cv = cv2.imread(img, cv2.IMREAD_COLOR)
        if img_cv is None:
            raise IOError("Failed to read %s because file is missing, "
                          "has improper permissions, or is an "
                          "unsupported or invalid format" % img)
    elif isinstance(img, np.ndarray):
        # don't try to convert an already-gray image to gray
        if grayscale and len(img.shape) == 3:  # and img.shape[2] == 3:
            img_cv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else: # input image is already a numpy array
            img_cv = img
    elif hasattr(img, 'convert'):
        # assume its a PIL.Image, convert to cv format
        img_array = np.array(img.convert('RGB'))
        img_cv = img_array[:, :, ::-1].copy()  # -1 does RGB -> BGR
        if grayscale:
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    else:
        raise TypeError('expected an image filename, OpenCV numpy array, or PIL image')
    return img_cv

def loadFromFile(pathName,absolute=False,grayscale=False):
    absPath = pathName
    if not absolute: absPath = joinPath(pathName)
    return loadImage(absPath,grayscale=grayscale)

def locate(templateImg,originImg,confidence=0.999,limit=100): # template: BGR, originImg: BGR
    # get all matches at once, credit: https://stackoverflow.com/questions/7670112/finding-a-subimage-inside-a-numpy-image/9253805#9253805
    result = cv2.matchTemplate(originImg, templateImg, cv2.TM_CCOEFF_NORMED)
    match_indices = np.arange(result.size)[(result > confidence).flatten()]
    matches = np.unravel_index(match_indices[:limit], result.shape)
    # use a generator for API consistency:
    for x, y in zip(matches[1], matches[0]):
        yield x,y

def locateImageInGame(targetImg,relRegion=None,confidence=None,absolute=True,windowName=globalWindowName): # relRegion: relative region in game, absolute: return absolute coords insteads of relative coords for mouse-clicking
    if relRegion is not None:
        assert len(relRegion)==4 , 'Error in locateImageInGame(): invalid relative region' # startX,startY,endX,endY
    gameCoord,hwnd = getWindowRectByName(windowName)
    try:
        originImgRGB = pyautogui.screenshot(region=gameCoord)
        originImg = cv2.cvtColor(np.asarray(originImgRGB),cv2.COLOR_RGB2BGR)
        if relRegion is not None:
            originImg = originImg[relRegion[0]:relRegion[2],relRegion[1]:relRegion[3]]
        if confidence is not None:
            results = tuple(locate(targetImg,originImg,confidence=confidence,limit=10))
        else: results = tuple(locate(targetImg,originImg,limit=10))
        if len(results) == 0: # Not Found
            return (-1,-1)
        # will return the center position
        bestResult = results[0]
        targetHeight, targetWidth = targetImg.shape[:2]
        if absolute:
            return gameCoord[0]+bestResult[0]+(targetWidth/2),gameCoord[1]+bestResult[1]+(targetHeight/2)
        return bestResult[0]+(targetWidth/2),bestResult[1]+(targetHeight/2)
    except:
        traceback.print_exc()
def isImageInGame(*args, **kwargs):
    return locateImageInGame(*args, **kwargs)[0]!=-1

def locateButtons(img,imgHL,confidence1=None,confidence2=None):
    if confidence1 is not None: imgLoc = locateImageInGame(img,confidence=confidence1)
    else: imgLoc = locateImageInGame(img)
    if confidence2 is not None: imgHL = locateImageInGame(imgHL,confidence=confidence2)
    else : imgHL = locateImageInGame(imgHL)
    if imgHL[0] == -1: return imgLoc
    if imgLoc[0] == -1: return imgHL

def filterColorInMask(origin,mask,highlight=False,dimensions=1):
    row,column = origin.shape[:2]
    for r in range(row):
        for c in range(column):
            if highlight is True:
                if mask.item(r,c) != 255:
                    if dimensions>1:
                        for i in range(0,dimensions):
                            origin.itemset((r,c,i),0)
                    else: 
                        origin.itemset((r,c),0)
            elif mask.item(r,c) == 255:
                if dimensions>1:
                    for i in range(0,dimensions):
                        origin.itemset((r,c,i),0)
                else: 
                    origin.itemset((r,c),0)
    return origin

def getWindowRectByHwnd(windowHwnd):
    left, top, right, bottom = win32gui.GetWindowRect(windowHwnd)
    w = right - left
    h = bottom - top
    return (left,top,w,h)

def getWindowRectByName(windowName):
    hwnd = win32gui.FindWindow(None, windowName)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w = right - left
    h = bottom - top
    return (left,top,w,h),hwnd

def getAbsoluteCoordByOffset(origin,offset):
    return origin[0]+offset[0],origin[1]+offset[1]

def getOffsetCoordByAbsolute(origin,abs): 
    return abs[0]-origin[0],abs[1]-origin[1]

def mouseClick(*args): # y=None to provide compability to Tuple
    argLength = len(args)
    assert argLength == 1 or argLength == 2, 'Error in mouseClick(): invalid argument'
    clickX = clickY = None
    if argLength == 1 and args[0][0]>=0 and args[0][1]>=0 : # Tuple
        clickX = args[0][0]
        clickY = args[0][1]
    elif argLength == 2 and args[0]>=0 and args[1]>=0 : # x,y
        clickX = args[0]
        clickY = args[1]
    pyautogui.mouseDown(clickX,clickY)
    time.sleep(MOUSE_CLICK_DELAY)
    pyautogui.mouseUp()
    return True

def isForegroundWindow(windowName,windowHwnd=None) -> bool:
    try:
        if windowHwnd==None: windowHwnd=win32gui.FindWindow(None, windowName)
        foregroundHwnd=win32gui.GetForegroundWindow()
        return windowHwnd==foregroundHwnd
    except: return False

def isFileOpen(filePath):
    try:
        fHandle = win32file.CreateFile(filePath,win32file.GENERIC_READ,0,None,win32file.OPEN_EXISTING,win32file.FILE_ATTRIBUTE_NORMAL,None)
        if int(fHandle) == win32file.INVALID_HANDLE_VALUE: # already opened and occupied
            return True
        win32file.CloseHandle(fHandle)
        return False
    except:
        return True

def killProcess(processName):
    os.system('TASKKILL /F /IM '+processName)

def isProcessExist(processName):
    pids = psutil.pids()
    for pid in pids:
        if psutil.Process(pid).name() == processName: return True
    return False

def stackAnalyser(stack:str):
    """
    Output file name and line from stacktrace
    Input: traceback.format_stack()
    Output: fileName,line
    """
    elements = stack.split(',')
    fileName = os.path.basename(elements[0].replace('File','').replace('"','').strip())
    line = re.findall(r"\d+",elements[1])[0]
    return fileName,line

def getKeys(d:dict, value):
    return [k for k,v in d.items() if v == value]

#Returns a (Left, Top, W, H) coordinate based off the game Window coordinates and the offset.
def getScreenShotRegion(gameCoord, offset):
    return gameCoord[0]+offset[0],gameCoord[1]+offset[1], offset[2], offset[3]

#Takes a screenshot in the game window of the specified region.
def getRegionScreenshot(region):
    return pyautogui.screenshot(region=region)

#Returns the text within the supplied image
def readText(img):
    img_np = np.array(img)
    return pytesseract.image_to_string(img_np)

#Returns only the integer version of credits read from image.
def parseCredits(input):
    text = input.replace(',','')
    text = text.replace(' CR', '')
    text = text.strip()
    return int(text)

#Returns a screenshot of the game window.  Can be used to determine what went wrong
#While script runs unattended.
def debugScreenshot(gameCoord, state, position):
    screen_dir = '/debug_screenshots/'
    os.path.join(os.path.dirname(os.cwd()), screen_dir)
    windowSize = (1600, 900)
    region = gameCoord + windowSize
    screenshot = pyautogui.screenshot(region=region)
    timestr = time.strftime("%Y-%m-%d-%H-%M-%S")
    filename = timestr + state + position
    screenshot.save(path + filename + '.png', 'png')

#Returns number with commas
def prettyNumber(input):
    return "{:,}".format(int(input))