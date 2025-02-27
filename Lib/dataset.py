# Automatically adapted for numpy.oldnumeric Aug 01, 2007 by foo
# Further modified to be pure new numpy June 24th 2008

""" CDMS dataset and file objects"""
from __future__ import print_function
from .error import CDMSError
import sys
from . import Cdunif
import numpy
from . import cdmsNode
import os
import string
try:
    from urllib.parse import urlparse, urlunparse
    from urllib.request import urlopen
except ImportError:
    from urlparse import urlparse, urlunparse
    from urllib import urlopen
from . import cdmsobj
import re
from .CDMLParser import CDMLParser
from .cdmsobj import CdmsObj
from .axis import Axis, FileAxis, FileVirtualAxis, isOverlapVector
from .coord import FileAxis2D, DatasetAxis2D
from .auxcoord import FileAuxAxis1D, DatasetAuxAxis1D
from .grid import RectGrid, FileRectGrid
from .hgrid import FileCurveGrid, DatasetCurveGrid
from .gengrid import FileGenericGrid, DatasetGenericGrid
from .variable import DatasetVariable
from .fvariable import FileVariable
from .tvariable import asVariable
from .cdmsNode import CdDatatypes
from . import convention
import warnings
from collections import OrderedDict
from six import string_types

# Default is serial mode until setNetcdfUseParallelFlag(1) is called
rk = 0
sz = 1
Cdunif.CdunifSetNCFLAGS("use_parallel", 0)
CdMpi = False

try:
    from mpi4py import rc
    rc.initialize = False
    from mpi4py import MPI
except BaseException:
    rk = 0

try:
    from . import gsHost
    from pycf import libCFConfig as libcf
except BaseException:
    libcf = None


DuplicateAxis = "Axis already defined: "


class DuplicateAxisError(CDMSError):
    pass


DuplicateGrid = "Grid already defined: "
DuplicateVariable = "Variable already defined: "
FileNotFound = "File not found: "
FileWasClosed = "File was closed: "
InvalidDomain = "Domain elements must be axes or grids"
ModeNotSupported = "Mode not supported: "
SchemeNotSupported = "Scheme not supported: "

# Regular expressions for parsing the file map.
_Name = re.compile(r'[a-zA-Z_:][-a-zA-Z0-9._:]*')
_ListStartPat = r'\[\s*'
_ListStart = re.compile(_ListStartPat)
_ListEndPat = r'\s*\]'
_ListEnd = re.compile(_ListEndPat)
_ListSepPat = r'\s*,\s*'
_ListSep = re.compile(_ListSepPat)
_IndexPat = r'(\d+|-)'
_FilePath = r"([^\s\]\',]+)"
# Two file map patterns, _IndexList4 is the original one, _IndexList5 supports
# forecast data too...
_IndexList4 = re.compile(
    _ListStartPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _FilePath +
    _ListEndPat)
_IndexList5 = re.compile(
    _ListStartPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _IndexPat +
    _ListSepPat +
    _FilePath +
    _ListEndPat)

_NPRINT = 20
_showCompressWarnings = True


def setCompressionWarnings(value=None):
    """Turn on/off the warnings for compression.

    Parameters
    ----------
    value : *  0/1 False/True 'no'/'yes' or None (which sets it to the opposite

    Returns
    -------
    Return set value.
    """
    global _showCompressWarnings
    if value is None:
        value = not _showCompressWarnings
    if isinstance(value, string_types):
        if not value.slower() in ['y', 'n', 'yes', 'no']:
            raise CDMSError(
                "setCompressionWarnings flags must be yes/no or 1/0, or None to invert it")
        if value.lower()[0] == 'y':
            value = 1
        else:
            value = 0
    if not isinstance(value, (int, bool)):
        raise CDMSError(
            "setCompressionWarnings flags must be yes/no or 1/0, or None to invert it")

    if value in [1, True]:
        _showCompressWarnings = True
    elif value in [0, False]:
        _showCompressWarnings = False
    else:
        raise CDMSError(
            "setCompressionWarnings flags must be yes\/no or 1\/0, or None to invert it")

    return _showCompressWarnings


def setNetcdfUseNCSwitchModeFlag(value):
    """Tells cdms2 to switch constantly between netcdf define/write modes.

       Parameters
       ----------
       value : 0/1, False/True.

       Returns
       -------
       No return value.
    """

    if value not in [True, False, 0, 1]:
        raise CDMSError(
            "Error UseNCSwitchMode flag must be 1(can use)/0(do not use) or true/False")
    if value in [0, False]:
        Cdunif.CdunifSetNCFLAGS("use_define_mode", 0)
    else:
        Cdunif.CdunifSetNCFLAGS("use_define_mode", 1)


def setNetcdfUseParallelFlag(value):
    """Enable/Disable NetCDF MPI I/O (Paralllelism).

       Parameters
       ----------
       value : 0/1, False/True.

       Returns
       -------
       No return value.
    """
    global CdMpi
    if value not in [True, False, 0, 1]:
        raise CDMSError(
            "Error UseParallel flag must be 1(can use)/0(do not use) or true/False")
    if value in [0, False]:
        Cdunif.CdunifSetNCFLAGS("use_parallel", 0)
    else:
        Cdunif.CdunifSetNCFLAGS("use_parallel", 1)
        CdMpi = True
        if not MPI.Is_initialized():
            MPI.Init()


def getMpiRank():
    """Return number of processor available.

       Returns
       -------
       rank or 0 if MPI is not enabled.
    """
    if CdMpi:
        rk = MPI.COMM_WORLD.Get_rank()
        return rk
    else:
        return 0


def getMpiSize():
    """Return MPI size.

       Returns
       -------
       MPI size or 0 if MPI is not enabled.
    """
    if CdMpi:
        sz = MPI.COMM_WORLD.Get_size()
        return sz
    else:
        return 1


def setNetcdf4Flag(value):
    """Enable netCDF4 (HDF5) mode in libnetcdf.

       Parameters
       ----------
       value : 0/1, False/True.

       Returns
       -------
       No return value.
    """
    if value not in [True, False, 0, 1]:
        raise CDMSError("Error NetCDF4 flag must be 1/0 or true/False")
    if value in [0, False]:
        Cdunif.CdunifSetNCFLAGS("netcdf4", 0)
    else:
        Cdunif.CdunifSetNCFLAGS("netcdf4", 1)


def setNetcdfClassicFlag(value):
    """Enable netCDF3 (classic) mode in libnetcdf.

       Parameters
       ----------
       value : 0/1, False/True.

       Returns
       -------
       No return value.
    """
    if value not in [True, False, 0, 1]:
        raise CDMSError("Error NetCDF Classic flag must be 1/0 or true/False")
    if value in [0, False]:
        Cdunif.CdunifSetNCFLAGS("classic", 0)
    else:
        Cdunif.CdunifSetNCFLAGS("classic", 1)


def setNetcdfShuffleFlag(value):
    """Enable/Disable NetCDF shuffle.

       Parameters
       ----------
       value : 0/1, False/True.

       Returns
       -------
       No return value.
    """
    if value not in [True, False, 0, 1]:
        raise CDMSError("Error NetCDF Shuffle flag must be 1/0 or true/False")
    if value in [0, False]:
        Cdunif.CdunifSetNCFLAGS("shuffle", 0)
    else:
        Cdunif.CdunifSetNCFLAGS("shuffle", 1)


def setNetcdfDeflateFlag(value):
    """Enable/Disable NetCDF deflattion.

       Parameters
       ----------
       value : 0/1, False/True.

       Returns
       -------
       No return value.
    """
    if value not in [True, False, 0, 1]:
        raise CDMSError("Error NetCDF deflate flag must be 1/0 or true/False")
    if value in [0, False]:
        Cdunif.CdunifSetNCFLAGS("deflate", 0)
    else:
        Cdunif.CdunifSetNCFLAGS("deflate", 1)


def setNetcdfDeflateLevelFlag(value):
    """Sets NetCDF deflate level flag value

       Parameters
       ----------
       value : Deflation Level 1-9.

       Returns
       -------
       No return value.
    """
    if value not in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]:
        raise CDMSError(
            "Error NetCDF deflate_level flag must be an integer < 10")
    Cdunif.CdunifSetNCFLAGS("deflate_level", value)


def getNetcdfUseNCSwitchModeFlag():
    """Get current netCDF define mode.

       Returns
       -------
       NetCDF define mode .
    """
    return Cdunif.CdunifGetNCFLAGS("use_define_mode")


def getNetcdfUseParallelFlag():
    """Get NetCDF UseParallel flag value.

       Parameters
       ----------
       value : 0/1, False/True

       Returns
       -------
       No return value.
    """
    return Cdunif.CdunifGetNCFLAGS("use_parallel")


def getNetcdf4Flag():
    """Get Net CD 4 Flag
       Returns
       -------
       NetCDF4 flag value.
    """
    return Cdunif.CdunifGetNCFLAGS("netcdf4")


def getNetcdfClassicFlag():
    """Get Net CDF Classic Flag

       Returns
       -------
       NetCDF classic flag value.
    """
    return Cdunif.CdunifGetNCFLAGS("classic")


def getNetcdfShuffleFlag():
    """Get Net CDF Shuffle Flag

       Returns
       -------
       NetCDF shuffle flag value.
    """
    return Cdunif.CdunifGetNCFLAGS("shuffle")


def getNetcdfDeflateFlag():
    """Get Net CDF Deflate Flag

       Returns
       -------
       NetCDF deflate flag value.
    """
    return Cdunif.CdunifGetNCFLAGS("deflate")


def getNetcdfDeflateLevelFlag():
    """Get Net CDF Deflate Level Flag

       Returns
       -------
       NetCDF deflate level flag value.
    """
    return Cdunif.CdunifGetNCFLAGS("deflate_level")


def useNetcdf3():
    """ Turns off (0) NetCDF flags for shuffle/cuDa/deflatelevel
    Output files are generated as NetCDF3 Classic after that

    Returns
    -------
    No return value.
    """
    setNetcdfShuffleFlag(0)
    setNetcdfDeflateFlag(0)
    setNetcdfDeflateLevelFlag(0)
    setNetcdf4Flag(0)

# Create a tree from a file path.
# Returns the parse tree root node.


def load(path):
    fd = open(path)
    text = fd.read()
    fd.close()
    p = CDMLParser()
    p.feed(text)
    p.close()
    return p.getRoot()

# Create a tree from a URI
# URI is of the form scheme://netloc/path;parameters?query#fragment
# where fragment may be an XPointer.
# Returns the parse tree root node.


def loadURI(uri):
    (scheme, netloc, path, parameters, query, fragment) = urlparse(uri)
    uripath = urlunparse((scheme, netloc, path, '', '', ''))
    fd = urlopen(uripath)
    text = fd.read()
    fd.close()
    p = CDMLParser()
    p.feed(text)
    p.close()
    return p.getRoot()

# Create a dataset
# 'path' is the XML file name, or netCDF filename for simple file create
# 'template' is a string template for the datafile(s), for dataset creation


def createDataset(path, template=None):
    """Create a dataset.

       Parameters
       ----------
       path : is the XML file name, or netCDF filename for simple file creation.

       template : is a string template for the datafile(s), for dataset creation.

       Returns
       -------
       writing file handle.
    """
    return openDataset(path, 'w', template)


# Open an existing dataset
# 'uri' is a Uniform Resource Identifier, referring to a cdunif file, XML file,
#   or LDAP URL of a catalog dataset entry.
# 'mode' is 'r', 'r+', 'a', or 'w'

def openDataset(uri, mode='r', template=None,
                dods=1, dpath=None, hostObj=None):
    """
    Open Dataset

    Parameters
    ----------
    uri : (str) Filename to open
    mode : (str) Either `r`,`w`,`a` mode to open the file in read/write/append
    template : A string template for the datafile(s), for dataset creation
    dods : (int) Default set to 1
    dpath : (str) Destination path.

    Returns
    -------
    file handle.
    """
    uri = uri.strip()
    (scheme, netloc, path, parameters, query, fragment) = urlparse(uri)
    if scheme in ('', 'file'):
        if netloc:
            # In case of relative path...
            path = netloc + path
        path = os.path.expanduser(path)
        path = os.path.normpath(os.path.join(os.getcwd(), path))

        root, ext = os.path.splitext(path)
        if ext in ['.xml', '.cdml']:
            if mode != 'r':
                raise ModeNotSupported(mode)
            datanode = load(path)
        else:
            # If the doesn't exist allow it to be created
            # Ok mpi has issues with bellow we need to test this only with 1
            # rank
            if not os.path.exists(path):
                return CdmsFile(path, mode, mpiBarrier=CdMpi)
            elif mode == "w":
                try:
                    os.remove(path)
                except BaseException:
                    pass
                return CdmsFile(path, mode, mpiBarrier=CdMpi)

            # The file exists
            file1 = CdmsFile(path, "r")
            if libcf is not None:
                if hasattr(file1, libcf.CF_FILETYPE):
                    if getattr(
                            file1, libcf.CF_FILETYPE) == libcf.CF_GLATT_FILETYPE_HOST:
                        file = gsHost.open(path, mode)
                    elif mode == 'r' and hostObj is None:
                        # helps performance on machines where file open (in
                        # CdmsFile) is costly
                        file = file1
                    else:
                        file = CdmsFile(path, mode, hostObj=hostObj)
                    file1.close()
                else:
                    file1.close()
                    file = CdmsFile(path, mode)
                return file
            else:
                file1.close()
                return CdmsFile(path, mode)
    elif scheme in ['http', 'gridftp', 'https']:

        if (dods):
            if mode != 'r':
                raise ModeNotSupported(mode)
            # DODS file?
            try:
                file = CdmsFile(uri, mode)
                return file
            except Exception:
                msg = "Error in DODS open of: " + uri
                if os.path.exists(os.path.join(
                        os.path.expanduser("~"), ".dodsrc")):
                    msg += "\nYou have a .dodsrc in your HOME directory, try to remove it"
                raise CDMSError(msg)
        else:
            try:
                datanode = loadURI(uri)
                return datanode
            except BaseException:
                datanode = loadURI(uri)
                raise CDMSError("Error in loadURI of: " + uri)

    else:
        raise SchemeNotSupported(scheme)

    # Determine dpath, the absolute path to data files:
    # dpath =
    # (1) head + node.directory, if .directory is relative
    # (2) node.directory, if absolute
    # (3) head, if no directory entry found (assume XML file is
    #       at top level of data directory)
    #
    # Note: In general, dset.datapath is relative to the URL of the
    #   enclosing database, but here the database is null, so the
    #   datapath should be absolute.
    if dpath is None:
        direc = datanode.getExternalAttr('directory')
        head = os.path.dirname(path)
        if direc and (os.path.isabs(direc) or urlparse(direc).scheme != ''):
            dpath = direc
        elif direc:
            dpath = os.path.join(head, direc)
        else:
            dpath = head

    dataset = Dataset(uri, mode, datanode, None, dpath)
    return dataset

# Functions for parsing the file map.


def parselist(text, f):
    """Parse a string of the form [A, A, ...].

       Parameters
       ----------
       text : Input String.

       f : function which parses A and returns (A, nconsumed).

       Returns
       -------
       Parser results.
       n number of matches.
    """

    n = 0
    m = _ListStart.match(text)
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[0:_NPRINT])
    result = []
    n += m.end()
    s, nconsume = f(text[n:])
    result.append(s)
    n += nconsume
    while True:
        m = _ListSep.match(text[n:])
        if m is None:
            break
        else:
            n += m.end()
        s, nconsume = f(text[n:])
        result.append(s)
        n += nconsume
    m = _ListEnd.match(text[n:])
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[n:n + _NPRINT])
    n += m.end()
    return result, n


def parseIndexList(text):
    """Parse a string of the form [i,j,k,l,...,path].

    Parameters
    ----------
    text : i,j,k,l,... are indices or '-', and path is a filename. Coerce the indices to integers.

    Returns
    -------
    Parser results.
    n number of matches.
    """
    m = _IndexList4.match(text)
    nindices = 4
    if m is None:
        m = _IndexList5.match(text)
        nindices = 5
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[0:_NPRINT])
    result = [None] * (nindices + 1)
    for i in range(nindices):
        s = m.group(i + 1)
        if s != '-':
            result[i] = int(s)
    result[nindices] = m.group(nindices + 1)
    return result, m.end()


def parseName(text):
    m = _Name.match(text)
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[0:_NPRINT])
    return m.group(), m.end()


def parseVarMap(text):
    """Parse a string of the form [ namelist, slicelist ]"""
    n = 0
    m = _ListStart.match(text)
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[0:_NPRINT])
    result = []
    n += m.end()
    s, nconsume = parselist(text[n:], parseName)
    result.append(s)
    n += nconsume
    m = _ListSep.match(text[n:])
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[n:n + _NPRINT])
    n += m.end()
    s, nconsume = parselist(text[n:], parseIndexList)
    result.append(s)
    n += nconsume
    m = _ListEnd.match(text[n:])
    if m is None:
        raise CDMSError("Parsing cdms_filemap near " + text[n:n + _NPRINT])
    n += m.end()
    return result, n


def parseFileMap(text):
    """Parse a CDMS filemap.

       Parameters
       ----------
       filemap : list [ varmap, varmap, ...]

       varmap : list [ namelist, slicelist ]

       namelist : list [name, name, ...]

       slicelist : list [indexlist, indexlist, ,,,]

       indexlist : list [i,j,k,l,path]

       Returns
       -------
       Parsing results.
    """
    result, n = parselist(text, parseVarMap)
    if n < len(text):
        raise CDMSError("Parsing cdms_filemap near " + text[n:n + _NPRINT])
    return result


# A CDMS dataset consists of a CDML/XML file and one or more data files
try:
    from .cudsinterface import cuDataset
except BaseException:
    pass


class Dataset(CdmsObj, cuDataset):

    def __init__(self, uri, mode, datasetNode=None,
                 parent=None, datapath=None):
        if datasetNode is not None and datasetNode.tag != 'dataset':
            raise CDMSError('Node is not a dataset node')
        CdmsObj.__init__(self, datasetNode)
        for v in ['datapath',
                  'variables',
                  'axes',
                  'grids',
                  'xlinks',
                  'dictdict',
                  'default_variable_name',
                  'parent',
                  'uri',
                  'mode']:
            if v not in self.__cdms_internals__:
                val = self.__cdms_internals__ + [v, ]
                self.___cdms_internals__ = val

        cuDataset.__init__(self)
        self.parent = parent
        self.uri = uri
        self.mode = mode
        # Path of data files relative to parent db.
        # Note: .directory is the location of data relative to the location of
        # the XML file
        self.datapath = datapath
        self.variables = {}
        self.axes = {}
        self.grids = {}
        self.xlinks = {}
        self._gridmap_ = {}
        # Gridmap:(latname,lonname,order,maskname,gridclass) => grid
        (scheme, netloc, xmlpath, parameters,
         query, fragment) = urlparse(uri)
        self._xmlpath_ = xmlpath
        # Dictionary of dictionaries, keyed on node tags
        self.dictdict = {'variable': self.variables,
                         'axis': self.axes,
                         'rectGrid': self.grids,
                         'curveGrid': self.grids,
                         'genericGrid': self.grids,
                         'xlink': self.xlinks
                         }
        # Dataset IDs are external, so may not have been defined yet.
        if not hasattr(self, 'id'):
            self.id = '<None>'
        self._status_ = 'open'
        self._convention_ = convention.getDatasetConvention(self)

        # Collect named children (having attribute 'id') into dictionaries
        if datasetNode is not None:
            coordsaux = self._convention_.getDsetnodeAuxAxisIds(datasetNode)

            for node in list(datasetNode.getIdDict().values()):
                if node.tag == 'variable':
                    if node.id in coordsaux:
                        if node.getDomain().getChildCount() == 1:
                            obj = DatasetAuxAxis1D(self, node.id, node)
                        else:
                            obj = DatasetAxis2D(self, node.id, node)
                    else:
                        obj = DatasetVariable(self, node.id, node)
                    self.variables[node.id] = obj
                elif node.tag == 'axis':
                    obj = Axis(self, node)
                    self.axes[node.id] = obj
                elif node.tag == 'rectGrid':
                    obj = RectGrid(self, node)
                    self.grids[node.id] = obj
#                elif node.tag == 'xlink':
#                    obj = Xlink(node)
#                    self.xlinks[node.id] = obj
                else:
                    dict = self.dictdict.get(node.tag)
                    if dict is not None:
                        dict[node.id] = node
                    else:
                        self.dictdict[node.tag] = {node.id: node}

            # Initialize grid domains
            for grid in list(self.grids.values()):
                grid.initDomain(self.axes, self.variables)
                latname = grid.getLatitude().id
                lonname = grid.getLongitude().id
                mask = grid.getMaskVar()
                if mask is None:
                    maskname = ""
                else:
                    maskname = mask.id
                self._gridmap_[
                    (latname, lonname, grid.getOrder(), maskname)] = grid

            # Initialize variable domains.
            for var in list(self.variables.values()):
                var.initDomain(self.axes, self.grids)

            for var in list(self.variables.values()):

                # Get grid information for the variable. gridkey has the form
                # (latname,lonname,order,maskname,abstract_class).
                gridkey, lat, lon = var.generateGridkey(
                    self._convention_, self.variables)

                # If the variable is gridded, lookup the grid. If no such grid exists,
                # create a unique gridname, create the grid, and add to the
                # gridmap.
                if gridkey is None:
                    grid = None
                else:
                    grid = self._gridmap_.get(gridkey)
                    if grid is None:
                        if hasattr(var, 'grid_type'):
                            gridtype = var.grid_type
                        else:
                            gridtype = "generic"

                        candidateBasename = None
                        if gridkey[4] == 'rectGrid':
                            gridshape = (len(lat), len(lon))
                        elif gridkey[4] == 'curveGrid':
                            gridshape = lat.shape
                        elif gridkey[4] == 'genericGrid':
                            gridshape = lat.shape
                            candidateBasename = 'grid_%d' % gridshape
                        else:
                            gridshape = (len(lat), len(lon))

                        if candidateBasename is None:
                            candidateBasename = 'grid_%dx%d' % gridshape
                        if candidateBasename not in self.grids:
                            gridname = candidateBasename
                        else:
                            foundname = 0
                            for i in range(97, 123):  # Lower-case letters
                                candidateName = candidateBasename + \
                                    '_' + chr(i)
                                if candidateName not in self.grids:
                                    gridname = candidateName
                                    foundname = 1
                                    break

                            if not foundname:
                                print(
                                    'Warning: cannot generate a grid for variable', var.id)
                                continue

                        # Create the grid
                        if gridkey[4] == 'rectGrid':
                            node = cdmsNode.RectGridNode(
                                gridname, lat.id, lon.id, gridtype, gridkey[2])
                            grid = RectGrid(self, node)
                            grid.initDomain(self.axes, self.variables)
                        elif gridkey[4] == 'curveGrid':
                            grid = DatasetCurveGrid(lat, lon, gridname, self)
                        else:
                            grid = DatasetGenericGrid(lat, lon, gridname, self)
                        self.grids[grid.id] = grid
                        self._gridmap_[gridkey] = grid

                # Set the variable grid
                var.setGrid(grid)

            # Attach boundary variables
            for name in coordsaux:
                var = self.variables[name]
                bounds = self._convention_.getVariableBounds(self, var)
                var.setBounds(bounds)

        # Create the internal filemap, if attribute 'cdms_filemap' is present.
        # _filemap_ is a dictionary, mapping (varname, timestart, levstart) => path
        #
        # Also, for each partitioned variable, set attribute '_varpart_' to [timepart, levpart]
        # where timepart is the partition for time (or None if not time-dependent)
        # and levpart is the partition in the level dimension, or None if not applicable.
        #
        # For variables partitioned in both time and level dimension, it is assumed that
        # for a given variable the partitions are orthogonal. That is, for a given
        # variable, at any timeslice the level partition is the same.
        if hasattr(self, 'cdms_filemap'):
            self._filemap_ = {}
            filemap = parseFileMap(self.cdms_filemap)
            for varlist, varmap in filemap:
                for varname in varlist:
                    timemap = {}
                    levmap = {}
                    fcmap = {}
                    # The for loop was:
                    # for tstart, tend, levstart, levend, path in varmap:
                    # but now there _may_ be an additional item before path...
                    for varm1 in varmap:
                        tstart, tend, levstart, levend = varm1[0:4]
                        if (len(varm1) >= 6):
                            forecast = varm1[4]
                        else:
                            forecast = None
                        path = varm1[-1]
                        self._filemap_[
                            (varname, tstart, levstart, forecast)] = path
                        if tstart is not None:
                            # Collect unique (tstart, tend) tuples
                            timemap[(tstart, tend)] = 1
                        if levstart is not None:
                            levmap[(levstart, levend)] = 1
                        if forecast is not None:
                            fcmap[(forecast, forecast)] = 1
                    tkeys = list(timemap.keys())
                    if len(tkeys) > 0:
                        tkeys.sort()
                        tpart = [list(x) for x in tkeys]
                    else:
                        tpart = None
                    levkeys = list(levmap.keys())
                    if len(levkeys) > 0:
                        levkeys.sort()
                        levpart = [list(x) for x in levkeys]
                    else:
                        levpart = None
                    fckeys = list(fcmap.keys())
                    if len(fckeys) > 0:
                        fckeys.sort()
                    if varname in self.variables:
                        self.variables[varname]._varpart_ = [tpart, levpart]

    def getConvention(self):
        """Get the metadata convention associated with this dataset or file."""
        return self._convention_

    # Get a dictionary of objects with the given tag
    def getDictionary(self, tag):
        return self.dictdict[tag]

    # Synchronize writes with data/metadata files
    def sync(self):
        pass

    # Close all files
    def close(self):
        for dict in list(self.dictdict.values()):
            for obj in list(dict.values()):
                obj.parent = None
                del obj
        self.dictdict = {}
        self.variables = {}
        self.axes = {}
        self.grids = {}
        self.xlinks = {}
        self.parent = None
        self._status_ = 'closed'

# Note: Removed to allow garbage collection of reference cycles
# def __del__(self):
# if cdmsobj._debug==1:
# print 'Deleting dataset',self.id
# self.close()

    # Create an axis
    # 'name' is the string name of the Axis
    # 'ar' is the 1-D data array, or None for an unlimited axis
    # Return an axis object.
    def createAxis(self, name, ar):
        pass

    # Create an implicit rectilinear grid. lat, lon, and mask are objects.
    # order and type are strings
    def createRectGrid(self, id, lat, lon, order, type="generic", mask=None):
        node = cdmsNode.RectGridNode(id, lat.id, lon.id, type, order, mask.id)
        grid = RectGrid(self, node)
        grid.initDomain(self.axes, self.variables)
        self.grids[grid.id] = grid
#        self._gridmap_[gridkey] = grid

    # Create a variable
    # 'name' is the string name of the Variable
    # 'datatype' is a CDMS datatype
    # 'axisnames' is a list of axes or grids
    # Return a variable object.
    def createVariable(self, name, datatype, axisnames):
        pass

    # Search for a pattern in a string-valued attribute. If attribute is None,
    # search all string attributes. If tag is 'dataset', just check the dataset,
    # else check all nodes in the dataset of class type matching the tag. If tag
    # is None, search the dataset and all objects contained in it.
    def searchPattern(self, pattern, attribute, tag):
        resultlist = []
        if tag is not None:
            tag = string.lower(tag)
        if tag in ('dataset', None):
            if self.searchone(pattern, attribute) == 1:
                resultlist = [self]
            else:
                resultlist = []
        if tag is None:
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    if obj.searchone(pattern, attribute):
                        resultlist.append(obj)
        elif tag != 'dataset':
            dict = self.dictdict[tag]
            for obj in list(dict.values()):
                if obj.searchone(pattern, attribute):
                    resultlist.append(obj)
        return resultlist

    # Match a pattern in a string-valued attribute. If attribute is None,
    # search all string attributes. If tag is 'dataset', just check the dataset,
    # else check all nodes in the dataset of class type matching the tag. If tag
    # is None, search the dataset and all objects contained in it.
    def matchPattern(self, pattern, attribute, tag):
        resultlist = []
        if tag is not None:
            tag = string.lower(tag)
        if tag in ('dataset', None):
            if self.matchone(pattern, attribute) == 1:
                resultlist = [self]
            else:
                resultlist = []
        if tag is None:
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    if obj.matchone(pattern, attribute):
                        resultlist.append(obj)
        elif tag != 'dataset':
            dict = self.dictdict[tag]
            for obj in list(dict.values()):
                if obj.matchone(pattern, attribute):
                    resultlist.append(obj)
        return resultlist

    # Apply a predicate, returning a list of all objects in the dataset
    # for which the predicate is true. The predicate is a function which
    # takes a dataset as an argument, and returns true or false. If the
    # tag is 'dataset', the predicate is applied to the dataset only.
    # If 'variable', 'axis', etc., it is applied only to that type of object
    # in the dataset. If None, it is applied to all objects, including
    # the dataset itself.
    def searchPredicate(self, predicate, tag):
        resultlist = []
        if tag is not None:
            tag = string.lower(tag)
        if tag in ('dataset', None):
            try:
                if predicate(*(self,)) == 1:
                    resultlist.append(self)
            except AttributeError:
                pass
        if tag is None:
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    try:
                        if predicate(*(obj,)) == 1:
                            resultlist.append(obj)
                    except AttributeError:
                        pass
        elif tag != "dataset":
            dict = self.dictdict[tag]
            for obj in list(dict.values()):
                try:
                    if predicate(*(obj,)) == 1:
                        resultlist.append(obj)
                except BaseException:
                    pass
        return resultlist

    # Return a sorted list of all data files associated with the dataset
    def getPaths(self):
        pathdict = {}
        for var in list(self.variables.values()):
            for path, stuple in var.getPaths():
                pathdict[path] = 1
        result = sorted(pathdict.keys())
        return result

    # Open a data file associated with this dataset.
    # <filename> is relative to the self.datapath
    # <mode> is the open mode.
    def openFile(self, filename, mode):

        # Opened via a local XML file?
        if self.parent is None:
            path = os.path.join(self.datapath, filename)
            if cdmsobj._debug == 1:
                sys.stdout.write(path + '\n')
                sys.stdout.flush()
            f = Cdunif.CdunifFile(path, mode)
            return f

        # Opened via a database
        else:
            dburls = self.parent.url
            if not isinstance(dburls, type([])):
                dburls = [dburls]

            # Try first to open as a local file
            for dburl in dburls:
                if os.path.isabs(self.directory):
                    fileurl = os.path.join(self.directory, filename)
                else:
                    try:
                        fileurl = os.path.join(dburl, self.datapath, filename)
                    except BaseException:
                        print(
                            'Error joining',
                            repr(dburl),
                            self.datapath,
                            filename)
                        raise
                (scheme, netloc, path, parameters, query,
                 fragment) = urlparse(fileurl)
                if scheme in ['file', ''] and os.path.isfile(path):
                    if cdmsobj._debug == 1:
                        sys.stdout.write(fileurl + '\n')
                        sys.stdout.flush()
                    f = Cdunif.CdunifFile(path, mode)
                    return f

            # See if request manager is being used for file transfer
            db = self.parent
            if db.usingRequestManager():
                cache = db.enableCache()
                lcbase = db.lcBaseDN
                lcpath = self.getLogicalCollectionDN(lcbase)

                # File location is logical collection path combined with
                # relative filename
                fileDN = (self.uri, filename)
                path = cache.getFile(
                    filename,
                    fileDN,
                    lcpath=lcpath,
                    userid=db.userid,
                    useReplica=db.useReplica)
                try:
                    f = Cdunif.CdunifFile(path, mode)
                except BaseException:                    # Try again, in case another process clobbered this file
                    path = cache.getFile(fileurl, fileDN)
                    f = Cdunif.CdunifFile(path, mode)
                return f

            # Try to read via FTP:

            for dburl in dburls:
                fileurl = os.path.join(dburl, self.datapath, filename)
                (scheme, netloc, path, parameters, query,
                 fragment) = urlparse(fileurl)
                if scheme == 'ftp':
                    cache = self.parent.enableCache()
                    fileDN = (self.uri, filename)  # Global file name
                    path = cache.getFile(fileurl, fileDN)
                    try:
                        f = Cdunif.CdunifFile(path, mode)
                    except BaseException:                        # Try again, in case another process clobbered this
                        # file
                        path = cache.getFile(fileurl, fileDN)
                        f = Cdunif.CdunifFile(path, mode)
                    return f

            # File not found
            raise FileNotFound(filename)

    def getLogicalCollectionDN(self, base=None):
        """Return the logical collection distinguished name of this dataset.

           Notes
           -----
           If <base> is defined, append it to the lc name.
        """
        if hasattr(self, "lc"):
            dn = self.lc
        else:
            dn = "lc=%s" % self.id
        if base is not None:
            dn = "%s,%s" % (dn, base)
        return dn

    def getVariable(self, id):
        """Get the variable object with the given id.

         Returns
         -------
         None if not found."""
        return self.variables.get(id)

    def getVariables(self, spatial=0):
        """Get a list of variable objects. If spatial=1, only return those
        axes defined on latitude or longitude, excluding weights and bounds."""
        retval = list(self.variables.values())
        if spatial:
            retval = [x for x in retval if x.id[
                0:7] != "bounds_" and x.id[
                0:8] != "weights_" and (
                (x.getLatitude() is not None) or (
                    x.getLongitude() is not None) or (
                    x.getLevel() is not None))]
        return retval

    def getAxis(self, id):
        """Get the axis object with the given id.

         Returns
         -------
         None if not found."""
        return self.axes.get(id)

    def getGrid(self, id):
        """Get the grid object with the given id.

         Returns
         -------
         None if not found."""
        return self.grids.get(id)

    def __repr__(self):
        return "<Dataset: '%s', URI: '%s', mode: '%s', status: %s>" % (
            self.id, self.uri, self.mode, self._status_)


# internattr.add_internal_attribute (Dataset, 'datapath',
# 'variables',
# 'axes',
# 'grids',
# 'xlinks',
# 'dictdict',
# 'default_variable_name',
# 'parent',
# 'uri',
# 'mode')


class CdmsFile(CdmsObj, cuDataset):

    def __init__(self, path, mode, hostObj=None, mpiBarrier=False):

        if mpiBarrier:
            MPI.COMM_WORLD.Barrier()

        CdmsObj.__init__(self, None)
        cuDataset.__init__(self)
        value = self.__cdms_internals__ + ['datapath',
                                           'variables',
                                           'axes',
                                           'grids',
                                           'xlinks',
                                           'dictdict',
                                           'default_variable_name',
                                           'id',
                                           'uri',
                                           'parent',
                                           'mode']
        self.___cdms_internals__ = value
        self.id = path
        if "://" in path:
            self.uri = path
        else:
            self.uri = "file://" + os.path.abspath(os.path.expanduser(path))
        self._mode_ = mode
        try:
            if mode[0].lower() == "w":
                try:
                    os.remove(path)
                except BaseException:
                    pass
            _fileobj_ = Cdunif.CdunifFile(path, mode)
        except Exception as err:
            raise CDMSError('Cannot open file %s (%s)' % (path, err))
        self._file_ = _fileobj_   # Cdunif file object
        self.variables = {}
        self.axes = {}
        self.grids = {}
        self.xlinks = {}
        self._gridmap_ = {}

        # self.attributes returns the Cdunif file dictionary.
# self.replace_external_attributes(self._file_.__dict__)
        for att in self._file_.__dict__.keys():
            self.__dict__.__setitem__(att, self._file_.__dict__[att])
            self.attributes[att] = self._file_.__dict__[att]
        self._boundAxis_ = None         # Boundary axis for cell vertices
        if self._mode_ == 'w':
            self.Conventions = convention.CFConvention.current
        self._status_ = 'open'
        self._convention_ = convention.getDatasetConvention(self)

        try:

            # A mosaic variable with coordinates attached, but the coordinate variables reside in a
            # different file. Add the coordinate variables to the mosaic
            # variables list.
            if hostObj is not None:
                for name in list(self._file_.variables.keys()):
                    if 'coordinates' in dir(self._file_.variables[name]):
                        coords = self._file_.variables[name].coordinates.split(
                        )
                        for coord in coords:
                            if coord not in list(self._file_.variables.keys()):
                                cdunifvar = Cdunif.CdunifFile(
                                    hostObj.gridVars[coord][0], mode)
                                self._file_.variables[coord] = cdunifvar.variables[coord]

            # Get lists of 1D and auxiliary coordinate axes
            coords1d = self._convention_.getAxisIds(self._file_.variables)
            coordsaux = self._convention_.getAxisAuxIds(
                self._file_.variables, coords1d)

            # Build variable list
            for name in list(self._file_.variables.keys()):
                if name not in coords1d:
                    cdunifvar = self._file_.variables[name]
                    if name in coordsaux:
                        # Put auxiliary coordinate axes with variables, since there may be
                        # a dimension with the same name.
                        if len(cdunifvar.shape) == 2:
                            self.variables[name] = FileAxis2D(
                                self, name, cdunifvar)
                        else:
                            self.variables[name] = FileAuxAxis1D(
                                self, name, cdunifvar)
                    else:
                        self.variables[name] = FileVariable(
                            self, name, cdunifvar)

            # Build axis list
            for name in sorted(self._file_.dimensions.keys()):
                if name in coords1d:
                    cdunifvar = self._file_.variables[name]
                elif name in coordsaux:
                    cdunifvar = self._file_.variables[name]
                else:
                    cdunifvar = None
                self.axes[name] = FileAxis(self, name, cdunifvar)
            self.axes = OrderedDict(sorted(self.axes.items()))

            # Attach boundary variables
            for name in coordsaux:
                var = self.variables[name]
                bounds = self._convention_.getVariableBounds(self, var)
                var.setBounds(bounds)

            self.dictdict = {
                'variable': self.variables,
                'axis': self.axes,
                'rectGrid': self.grids,
                'curveGrid': self.grids,
                'genericGrid': self.grids}

            # Initialize variable domains
            for var in list(self.variables.values()):
                var.initDomain(self.axes)

            # Build grids
            for var in list(self.variables.values()):
                # Get grid information for the variable. gridkey has the form
                # (latname,lonname,order,maskname, abstract_class).
                gridkey, lat, lon = var.generateGridkey(
                    self._convention_, self.variables)

                # If the variable is gridded, lookup the grid. If no such grid exists,
                # create a unique gridname, create the grid, and add to the
                # gridmap.
                if gridkey is None:
                    grid = None
                else:
                    grid = self._gridmap_.get(gridkey)
                    if grid is None:

                        if hasattr(var, 'grid_type'):
                            gridtype = var.grid_type
                        else:
                            gridtype = "generic"

                        candidateBasename = None
                        if gridkey[4] == 'rectGrid':
                            gridshape = (len(lat), len(lon))
                        elif gridkey[4] == 'curveGrid':
                            gridshape = lat.shape
                        elif gridkey[4] == 'genericGrid':
                            gridshape = lat.shape
                            candidateBasename = 'grid_%d' % gridshape
                        else:
                            gridshape = (len(lat), len(lon))

                        if candidateBasename is None:
                            candidateBasename = 'grid_%dx%d' % gridshape
                        if candidateBasename not in self.grids:
                            gridname = candidateBasename
                        else:
                            foundname = 0
                            for i in range(97, 123):  # Lower-case letters
                                candidateName = candidateBasename + \
                                    '_' + chr(i)
                                if candidateName not in self.grids:
                                    gridname = candidateName
                                    foundname = 1
                                    break

                            if not foundname:
                                print(
                                    'Warning: cannot generate a grid for variable', var.id)
                                continue

                        # Create the grid
                        if gridkey[4] == 'rectGrid':
                            grid = FileRectGrid(
                                self, gridname, lat, lon, gridkey[2], gridtype)
                        else:
                            if gridkey[3] != '':
                                if gridkey[3] in self.variables:
                                    maskvar = self.variables[gridkey[3]]
                                else:
                                    print(
                                        'Warning: mask variable %s not found' %
                                        gridkey[3])
                                    maskvar = None
                            else:
                                maskvar = None
                            if gridkey[4] == 'curveGrid':
                                grid = FileCurveGrid(
                                    lat, lon, gridname, parent=self, maskvar=maskvar)
                            else:
                                try:
                                    grid = FileGenericGrid(
                                        lat, lon, gridname, parent=self, maskvar=maskvar)
                                except BaseException:
                                    if(lat.rank() == 1 and lon.rank() == 1):
                                        grid = FileRectGrid(
                                            self, gridname, lat, lon, gridkey[2], gridtype)

                        self.grids[grid.id] = grid
                        self._gridmap_[gridkey] = grid

                # Set the variable grid
                var.setGrid(grid)
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        if type is None:
            self.close()
        else:
            return False
    # setattr writes external global attributes to the file

    def __setattr__(self, name, value):
        self.__dict__[name] = value  # attributes kept in sync w/file
        if name not in self.__cdms_internals__ and name[0] != '_':
            setattr(self._file_, name, value)
            self.attributes[name] = value

# getattr reads external global attributes from the file
# def __getattr__ (self, name):
# g = self.get_property_g(name)
# if g is not None:
# return g(self, name)
# if name in self.__cdms_internals__:
# try:
# return self.__dict__[name]
# except KeyError:
# raise AttributeError("%s instance has no attribute %s." % \
# (self.__class__.__name__, name))
# else:
# return getattr(self._file_,name)

    # delattr deletes external global attributes in the file
    def __delattr__(self, name):
        try:
            del self.__dict__[name]
        except KeyError:
            raise AttributeError("%s instance has no attribute %s." %
                                 (self.__class__.__name__, name))
        if name not in self.__cdms_internals__:
            delattr(self._file_, name)
            if(name in list(self.attributes.keys())):
                del(self.attributes[name])

    def sync(self):
        """
        Syncs the file on disk.
        """
        if self._status_ == "closed":
            raise CDMSError(FileWasClosed + self.id)
        self._file_.sync()

    def close(self):
        if self._status_ == "closed":
            return
        if hasattr(self, 'dictdict'):
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    obj.parent = None
                    del obj
        self.dictdict = self.variables = self.axes = {}
        self._file_.close()
        self._status_ = 'closed'

# Note: Removed to allow garbage collection of reference cycles
# def __del__(self):
# if cdmsobj._debug==1:
# print 'Deleting file',self.id
# If the object has been deallocated due to open error,
# it will not have an attribute .dictdict
# if hasattr(self,"dictdict") and self.dictdict != {}:
# self.close()

    # Create an axis
    # 'name' is the string name of the Axis
    # 'ar' is the 1-D data array, or None for an unlimited axis
    # Set unlimited to true to designate the axis as unlimited
    # Return an axis object.
    def createAxis(self, name, ar, unlimited=0):
        """
        Create an axis.

        Parameters
        ----------
        name : str is the string name of the Axis

        ar :  numpy.ndarray/None is the 1-D data array, or None for an unlimited axis

        unlimited : (int/True/False) True/0 designate that the axis as unlimited.

        Returns
        -------
        an axis object (cdms2.axis.FileAxis).
        """
        if self._status_ == "closed":
            raise CDMSError(FileWasClosed + self.id)
        cufile = self._file_
        if ar is None or (unlimited == 1 and getNetcdfUseParallelFlag() == 0):
            cufile.createDimension(str(name), None)
            if ar is None:
                typecode = numpy.dtype(numpy.float).char
            else:
                typecode = ar.dtype.char
        else:
            cufile.createDimension(str(name), len(ar))
            typecode = ar.dtype.char

        # Compatibility: revert to old typecode for cdunif
#        typecode = typeconv.oldtypecodes[typecode]
        cuvar = cufile.createVariable(str(name), typecode, (str(name),))

        # Cdunif should really create this extra dimension info:
        #   (units,typecode,filename,varname_local,dimension_type,ncid)
        cufile.dimensioninfo[str(name)] = ('', typecode, str(name), '', 'global', -1)

        # Note: like netCDF-3, cdunif does not support 64-bit integers.
        # If ar has dtype int64 on a 64-bit machine, cuvar will be a 32-bit int,
        # and ar must be downcast.
        if ar is not None:
            if ar.dtype.char != 'l':
                cuvar[0:len(ar)] = numpy.ma.filled(ar)
            else:
                cuvar[0:len(ar)] = numpy.ma.filled(ar).astype(cuvar.typecode())
        axis = FileAxis(self, name, cuvar)
        self.axes[name] = axis
        return axis

    def createVirtualAxis(self, name, axislen):
        """Create an axis without any associated coordinate array. This
        axis is read-only. This is useful for the 'bound' axis.

        Parameters
        ----------
        name : is the string name of the axis.

        axislen : is the integer length of the axis.

        Returns
        -------
        axis : file axis whose id is name (cdms2.axis.FileVirtualAxis)

        Notes
        -----
        For netCDF output, this just creates a dimension without
        the associated coordinate array. On reads the axis will look like
        an axis of type float with values [0.0, 1.0, ..., float(axislen-1)].
        On write attempts an exception is raised.
        """
        if self._status_ == "closed":
            raise CDMSError(FileWasClosed + self.id)
        cufile = self._file_
        cufile.createDimension(str(name), axislen)
        cufile.dimensioninfo[str(name)] = ('', 'f', str(name), '', 'global', -1)
        axis = FileVirtualAxis(self, str(name), axislen)
        self.axes[str(name)] = axis
        return axis

    # Copy axis description and data from another axis
    def copyAxis(self, axis, newname=None, unlimited=0,
                 index=None, extbounds=None):
        """Copy axis description and data from another axis.

        Parameters
        ----------
        axis : axis to copy (cdms2.axis.FileAxis/cdms2.axis.FileVirtualAxis)

        newname : (None/str) new name for axis (default None)

        unlimited : (int/True/False) unlimited dimension (default 0)

        index : (int/None) (default None)

        extbounds : (numpy.ndarray) new bounds to use bounds (default None)

        Returns
        --------
        copy of input axis (cdms2.axis.FileAxis/cdms2.axis.FileVirtualAxis)
        """
        if newname is None:
            newname = axis.id

        if len(newname) > 127:
            msg = "axis name has more than 127 characters, name will be truncated"
            warnings.warn(msg, UserWarning)
            newname = newname[:127] if len(newname) > 127 else newname

        # If the axis already exists and has the same values, return existing
        if newname in self.axes:
            newaxis = self.axes[newname]
            if newaxis.isVirtual():
                if len(axis) != len(newaxis):
                    raise DuplicateAxisError(DuplicateAxis + newname)
            elif unlimited == 0 or (unlimited == 1 and getNetcdfUseParallelFlag() != 0):
                if len(axis) != len(newaxis) or numpy.alltrue(
                        numpy.less(numpy.absolute(newaxis[:] - axis[:]), 1.e-5)) == 0:
                    raise DuplicateAxisError(DuplicateAxis + newname)
            else:
                if index is None:
                    isoverlap, index = isOverlapVector(axis[:], newaxis[:])
                else:
                    isoverlap = 1
                if isoverlap:
                    self._file_.sync()
                    newaxis[index:index + len(axis)] = axis[:]
                    if extbounds is None:
                        axisBounds = axis.getBounds()
                    else:
                        axisBounds = extbounds
                    if axisBounds is not None:
                        newaxis.setBounds(axisBounds)
                else:
                    raise DuplicateAxisError(DuplicateAxis + newname)

        elif axis.isVirtual():
            newaxis = self.createVirtualAxis(newname, len(axis))

        # Else create the new axis and copy its bounds and metadata
        else:
            newaxis = self.createAxis(newname, axis[:], unlimited)
            bounds = axis.getBounds()
            if bounds is not None:
                if hasattr(axis, 'bounds'):
                    boundsid = axis.bounds
                else:
                    boundsid = None
                newaxis.setBounds(bounds, persistent=1, boundsid=boundsid)
            for attname, attval in axis.attributes.items():
                if attname not in ["datatype", "id", "length",
                                   "isvar", "name_in_file", "partition"]:
                    setattr(newaxis, attname, attval)
        return newaxis

    # Create an implicit rectilinear grid. lat, lon, and mask are objects.
    # order and type are strings
    def createRectGrid(self, id, lat, lon, order, type="generic", mask=None):
        """
        Create an implicit rectilinear grid. lat, lon, and mask are objects. order and type are strings.

        Parameters
        ----------
        id : (str) grid name (default 0)

        lat : (numpy.ndarray) latitude array (default 1)

        lon : (numpy.ndarray) longitude array (default 2)

        order : (str) order (default 3)

        type : (str) grid type (defalut `generic`)

        mask : (None/numpy.ndarray) mask (default None)

        Returns
        -------
        grid (cdms2.grid.FileRectGrid)

        """
        grid = FileRectGrid(self, id, lat, lon, order, type, mask)
        self.grids[grid.id] = grid
        gridkey = (lat.id, lon.id, order, None)
        self._gridmap_[gridkey] = grid
        return grid

    # Copy grid
    def copyGrid(self, grid, newname=None):
        """
        Create an implicit rectilinear grid. lat, lon, and mask are objects. Order and type are strings.

        Parameters
        ----------
        newname : (str/None) new name for grid (default None)

        grid : file grid
               (cdms2.grid.FileRectGrid/cdms2.hgrid.FileCurveGrid/cdms2.gengrid.FileGenericGrid)

        Returns
        -------
        file grid
        (cdms2.grid.FileRectGrid/cdms2.hgrid.FileCurveGrid/cdms2.gengrid.FileGenericGrid)

        """
        if newname is None:
            if hasattr(grid, 'id'):
                newname = grid.id
            else:
                newname = 'Grid'

        oldlat = grid.getLatitude()
        if not hasattr(oldlat, 'id'):
            oldlat.id = 'latitude'
        oldlon = grid.getLongitude()
        if not hasattr(oldlon, 'id'):
            oldlon.id = 'longitude'
        lat = self.copyAxis(oldlat)
        lat.designateLatitude(persistent=1)
        lon = self.copyAxis(oldlon)
        lon.designateLongitude(persistent=1)

        # If the grid name already exists, and is the same, just return it
        if newname in self.grids:
            newgrid = self.grids[newname]
            newlat = newgrid.getLatitude()
            newlon = newgrid.getLongitude()
            if ((newlat is not lat) or
                (newlon is not lon) or
                (newgrid.getOrder() != grid.getOrder()) or
                    (newgrid.getType() != grid.getType())):
                raise DuplicateGrid(newname)

        # else create a new grid and copy metadata
        else:
            newmask = grid.getMask()    # Get the mask array
            newgrid = self.createRectGrid(
                newname, lat, lon, grid.getOrder(), grid.getType(), None)
            newgrid.setMask(newmask)    # Set the mask array, non-persistently
            for attname in list(grid.attributes.keys()):
                setattr(newgrid, attname, getattr(grid, attname))

        return newgrid

    # Create a variable
    # 'name' is the string name of the Variable
    # 'datatype' is a CDMS datatype or numpy typecode
    # 'axesOrGrids' is a list of axes, grids. (Note: this should be
    #   generalized to allow subintervals of axes and/or grids)
    # Return a variable object.
    def createVariable(self, name, datatype, axesOrGrids, fill_value=None):
        """
        Create a variable.

        Parameters
        ----------

        name : The string name of the Variable

        datatype : A CDMS datatype or numpy typecode

        axesOrGrids : is a list of axes, grids.

        fill_value : fill_value (cast into data type).

        Notes
        -----
        This should be generalized to allow subintervals of axes and/or grids.

        Returns
        -------
        Return a variable object (cdms2.fvariable.FileVariable.
        """
        if self._status_ == "closed":
            raise CDMSError(FileWasClosed + self.id)
        cufile = self._file_
        if datatype in CdDatatypes:
            numericType = cdmsNode.CdToNumericType.get(datatype)
        else:
            numericType = datatype

        # Make a list of names of axes for _Cdunif
        dimensions = []
        for obj in axesOrGrids:
            if isinstance(obj, FileAxis):
                dimensions.append(str(obj.id))
            elif isinstance(obj, FileRectGrid):
                dimensions = dimensions + \
                    [str(obj.getAxis(0).id), str(obj.getAxis(1).id)]
            else:
                raise InvalidDomain

        try:
            # Compatibility: revert to old typecode for cdunif
            #            numericType = typeconv.oldtypecodes[numericType]
            numericType = numpy.dtype(numericType).char
            cuvar = cufile.createVariable(str(name), numericType, tuple(dimensions))
        except Exception as err:
            print(err)
            raise CDMSError("Creating variable " + name)
        var = FileVariable(self, name, cuvar)
        var.initDomain(self.axes)
        self.variables[name] = var
        if fill_value is not None:
            var.setMissing(fill_value)
        return var

    # Search for a pattern in a string-valued attribute. If attribute is None,
    # search all string attributes. If tag is 'cdmsFile', just check the dataset,
    # else check all nodes in the dataset of class type matching the tag. If tag
    # is None, search the dataset and all objects contained in it.
    def searchPattern(self, pattern, attribute, tag):
        """
        Search for a pattern in a string-valued attribute. If attribute is None, search all
        string attributes.

        If tag is not None, it must match the internal node tag.

        Parameters
        ----------

        pattern : expression pattern

        attribute : attribute name

        tag : node tag

        Returns
        -------
        list of match pattern
        """
        resultlist = []
        if tag is not None:
            tag = string.lower(tag)
        if tag in ('cdmsFile', None, 'dataset'):
            if self.searchone(pattern, attribute) == 1:
                resultlist = [self]
            else:
                resultlist = []
        if tag is None:
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    if obj.searchone(pattern, attribute):
                        resultlist.append(obj)
        elif tag not in ('cdmsFile', 'dataset'):
            dict = self.dictdict[tag]
            for obj in list(dict.values()):
                if obj.searchone(pattern, attribute):
                    resultlist.append(obj)
        return resultlist

    # Match a pattern in a string-valued attribute. If attribute is None,
    # search all string attributes. If tag is 'cdmsFile', just check the dataset,
    # else check all nodes in the dataset of class type matching the tag. If tag
    # is None, search the dataset and all objects contained in it.
    def matchPattern(self, pattern, attribute, tag):
        """
        Match for a pattern in a string-valued attribute. If attribute is None,
        search all string attributes. If tag is not None, it must match the internal node tag.

        Parameters
        ----------
        pattern : String expression.

        attribute : Attribute Name. If `None` search all attributre.

        tag : node tag, if `cdmsFile` only match the current dataset otherwise match
              all object matching the tag.

        Returns
        -------
        list of match patterns.
        """
        resultlist = []
        if tag is not None:
            tag = string.lower(tag)
        if tag in ('cdmsFile', None, 'dataset'):
            if self.matchone(pattern, attribute) == 1:
                resultlist = [self]
            else:
                resultlist = []
        if tag is None:
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    if obj.matchone(pattern, attribute):
                        resultlist.append(obj)
        elif tag not in ('cdmsFile', 'dataset'):
            dict = self.dictdict[tag]
            for obj in list(dict.values()):
                if obj.matchone(pattern, attribute):
                    resultlist.append(obj)
        return resultlist

    # Apply a predicate, returning a list of all objects in the dataset
    # for which the predicate is true. The predicate is a function which
    # takes a dataset as an argument, and returns true or false. If the
    # tag is 'cdmsFile', the predicate is applied to the dataset only.
    # If 'variable', 'axis', etc., it is applied only to that type of object
    # in the dataset. If None, it is applied to all objects, including
    # the dataset itself.
    def searchPredicate(self, predicate, tag):
        """
        Apply a truth-valued predicate.

        Parameters
        ----------
        predicate : function use as predicate

        tag : node tag.

        Returns
        -------
        List containing a single instance [self] if the predicate is true and either
        tag is None or matches the object node tag.

        Empty list If the predicate returns false.
        """
        resultlist = []
        if tag is not None:
            tag = string.lower(tag)
        if tag in ('cdmsFile', None, 'dataset'):
            try:
                if predicate(*(self,)) == 1:
                    resultlist.append(self)
            except AttributeError:
                pass
        if tag is None:
            for dict in list(self.dictdict.values()):
                for obj in list(dict.values()):
                    try:
                        if predicate(*(obj,)) == 1:
                            resultlist.append(obj)
                    except AttributeError:
                        pass
        elif tag not in ('dataset', 'cdmsFile'):
            dict = self.dictdict[tag]
            for obj in list(dict.values()):
                try:
                    if predicate(*(obj,)) == 1:
                        resultlist.append(obj)
                except BaseException:
                    pass
        return resultlist

    def createVariableCopy(self, var, id=None, attributes=None, axes=None, extbounds=None,
                           extend=0, fill_value=None, index=None, newname=None, grid=None):
        """Define a new variable, with the same axes and attributes as in <var>.

        Note
        ----
        This function does not copy the data itself.

        Parameters
        ----------
        var : variable to copy (cdms2.tvariable.TransientVariable or cdms2.fvariable.FileVariable)

        attributes : A dictionary of attributes. Default is var.attributes.

        axes : The list of axis objects. Default is var.getAxisList()

        extbounds : Bounds of the (portion of) the extended dimension being written.

        id or newname : String identifier of the new variable.

        extend :
            * 1 define the first dimension as the unlimited dimension.
            * 0 do not define an unlimited dimension. The default is the define
                the first dimension as unlimited only if it is a time dimension.

        fill_value : The missing value flag.

        index : The extended dimension index for writting. The default index is determined
                by lookup relative to the existing extended dimension.

        grid : The variable grid.  `none` the value of var.getGrid() will used.

        Returns
        -------
        file variable (cdms2.fvariable.FileVariable)
        """
        if newname is None:
            newname = var.id
        if id is not None:
            newname = id
        if newname in self.variables:
            raise DuplicateVariable(newname)

        # Determine the extended axis name if any
        if axes is None:
            sourceAxislist = var.getAxisList()
        else:
            sourceAxislist = axes

        if var.rank() == 0:      # scalars are not extensible
            extend = 0

        if extend in (1, None):
            firstAxis = sourceAxislist[0]
            if firstAxis is not None and (extend == 1 or firstAxis.isTime()):
                extendedAxis = firstAxis.id
            else:
                extendedAxis = None
        else:
            extendedAxis = None

        # Create axes if necessary
        axislist = []
        for axis in sourceAxislist:
            # classic does not handle int64 data
            if((axis[:].dtype == numpy.int64) and Cdunif.CdunifGetNCFLAGS("classic")):
                axis._data_ = numpy.array(axis[:], dtype=numpy.int32)
            if extendedAxis is None or axis.id != extendedAxis:
                try:
                    newaxis = self.copyAxis(axis)
                except DuplicateAxisError:

                    # Create a unique axis name
                    setit = 0
                    for i in range(97, 123):  # Lower-case letters
                        try:
                            newaxis = self.copyAxis(
                                axis, axis.id + '_' + chr(i))
                            setit = 1
                            break
                        except DuplicateAxisError:
                            continue

                    if setit == 0:
                        raise DuplicateAxisError(DuplicateAxis + axis.id)
            else:
                newaxis = self.copyAxis(
                    axis, unlimited=1, index=index, extbounds=extbounds)

            axislist.append(newaxis)

        # Copy variable metadata
        if attributes is None:
            attributes = var.attributes
            try:
                attributes['missing_value'] = var.missing_value
            except Exception as err:
                print(err)
                pass
            try:
                if fill_value is None:
                    if('_FillValue' in attributes.keys()):
                        attributes['_FillValue'] = numpy.array(
                            var._FillValue).astype(var.dtype)
                        attributes['missing_value'] = numpy.array(
                            var._FillValue).astype(var.dtype)
                    if('missing_value' in attributes.keys()):
                        attributes['_FillValue'] = numpy.array(
                            var.missing_value).astype(var.dtype)
                        attributes['missing_value'] = numpy.array(
                            var.missing_value).astype(var.dtype)
                else:
                    attributes['_FillValue'] = numpy.array(
                        fill_value).astype(var.dtype)
                    attributes['missing_value'] = numpy.array(
                        fill_value).astype(var.dtype)
            except BaseException:
                pass
            if "name" in attributes:
                if attributes['name'] != var.id:
                    del(attributes['name'])

        # Create grid as necessary
        if grid is None:
            grid = var.getGrid()
        if grid is not None:
            coords = grid.writeToFile(self)
            if coords is not None:
                coordattr = "%s %s" % (coords[0].id, coords[1].id)
                if attributes is None:
                    attributes = {'coordinates': coordattr}
                else:
                    attributes['coordinates'] = coordattr

        # Create the new variable
        datatype = cdmsNode.NumericToCdType.get(var.typecode())
        newvar = self.createVariable(str(newname), datatype, axislist)
        for attname, attval in list(attributes.items()):
            if attname not in ["id", "datatype", "parent"]:
                if isinstance(attval, string_types):
                    attval = str(attval)
                setattr(newvar, str(attname), attval)
                if (attname == "_FillValue") or (attname == "missing_value"):
                    setattr(newvar, "_FillValue", attval)
                    setattr(newvar, "missing_value", attval)

        if fill_value is not None:
            newvar.setMissing(fill_value)

        return newvar

    def write(self, var, attributes=None, axes=None, extbounds=None, id=None,
              extend=None, fill_value=None, index=None, typecode=None, dtype=None, pack=False):
        """Write var to the file.

        Notes
        -----
        If the variable is not yet defined in the file, a definition is created.
        By default, the time dimension of the variable is defined as the
        `extended dimension` of the file. The function returns the corresponding file variable.

        Parameters
        ----------

        var : variable to copy.

        attributes : The attribute dictionary for the variable. The default is var.attributes.

        axes : The list of file axes comprising the domain of the variable. The default is to
               copy var.getAxisList().

        extbounds : The extended dimension bounds. Defaults to var.getAxis(0).getBounds().

        id : The variable name in the file. Default is var.id.

        extend :
              * 1 causes the first dimension to be `extensible` iteratively writeable.
                The default is None, in which case the first dimension is extensible if it is time.
              * 0 to turn off this behaviour.

        fill_value : is the missing value flag.

        index : The extended dimension index to write to. The default index is determined b
                lookup relative to the existing extended dimension.

        dtype : The numpy dtype.

        typecode : Deprecated, for backward compatibility only

        Returns
        -------
        File variable
        """
        if _showCompressWarnings:
            if (Cdunif.CdunifGetNCFLAGS("shuffle") != 0) or (Cdunif.CdunifGetNCFLAGS(
                    "deflate") != 0) or (Cdunif.CdunifGetNCFLAGS("deflate_level") != 0):
                import warnings
                warnings.warn("Files are written with compression and no shuffling\n" +
                              "You can query different values of compression using the functions:\n" +
                              "cdms2.getNetcdfShuffleFlag() returning 1 if shuffling is enabled, " +
                              "0 otherwise\ncdms2.getNetcdfDeflateFlag() returning 1 if deflate is used, " +
                              "0 otherwise\ncdms2.getNetcdfDeflateLevelFlag() " +
                              "returning the level of compression for the deflate method\n\n" +
                              "If you want to turn that off or set different values of compression " +
                              "use the functions:\nvalue = 0\ncdms2.setNetcdfShuffleFlag(value) " +
                              "## where value is either 0 or 1\ncdms2.setNetcdfDeflateFlag(value) " +
                              "## where value is either 0 or 1\ncdms2.setNetcdfDeflateLevelFlag(value) " +
                              "## where value is a integer between 0 and 9 included\n\nTo " +
                              "produce NetCDF3 Classic files use:\ncdms2.useNetCDF3()\n" +
                              "To Force NetCDF4 output with " +
                              "classic format and no compressing use:\ncdms2.setNetcdf4Flag(1)\n" +
                              "NetCDF4 file with no shuffling or deflate and noclassic will be open " +
                              "for parallel i/o", Warning)

        # Make var an AbstractVariable
        if dtype is None and typecode is not None:
            #            dtype = typeconv.convtypecode2(typecode)
            dtype = typecode
        typecode = dtype
        if typecode is not None and var.dtype.char != typecode:
            var = var.astype(typecode)
        if var.dtype.char == 'l' and Cdunif.CdunifGetNCFLAGS("classic"):
            var = var.astype(numpy.int32)
        if var.dtype.char == 'L' and Cdunif.CdunifGetNCFLAGS("classic"):
            var = var.astype(numpy.uint32)
        var = asVariable(var, writeable=0)

        if fill_value is None and hasattr(var, "fill_value"):
            fill_value = var.fill_value
        # Define the variable if necessary.
        if id is None:
            varid = var.id
        else:
            varid = id

        if len(varid) > 127:
            msg = "varid name has more than 127 characters, name will be truncate"
            warnings.warn(msg, UserWarning)
            varid = varid[:127] if len(varid) > 127 else varid

        if varid in self.variables:
            if pack:
                raise CDMSError(
                    "You cannot pack an existing variable %s " %
                    varid)
            v = self.variables[varid]
        else:
            if pack is not False:
                typ = numpy.int16
                n = 16
            else:
                typ = var.dtype
            v = self.createVariableCopy(var.astype(typ), attributes=attributes, axes=axes, extbounds=extbounds,
                                        id=varid, extend=extend, fill_value=fill_value, index=index)

        # If var has typecode numpy.int, and v is created from var, then v will have
        # typecode numpy.int32. (This is a Cdunif 'feature'). This causes a downcast error
        # for numpy versions 23+, so make the downcast explicit.
        if var.typecode() == numpy.int and v.typecode() == numpy.int32 and pack is False:
            var = var.astype(numpy.int32)

        # Write
        if axes is None:
            sourceAxislist = var.getAxisList()
        else:
            sourceAxislist = axes

        vrank = var.rank()
        if vrank == 0:      # scalars are not extensible
            extend = 0
        else:
            vec1 = sourceAxislist[0]

        if extend == 0 or (extend is None and not vec1.isTime()):
            if vrank > 0:
                if pack is not False:
                    v[:] = numpy.zeros(var.shape, typ)
                else:
                    v[:] = var.astype(v.dtype)
            else:
                v.assignValue(var.getValue())
        else:
            # Determine if the first dimension of var overlaps the first
            # dimension of v
            vec2 = v.getAxis(0)
            if extbounds is None:
                bounds1 = vec1.getBounds()
            else:
                bounds1 = extbounds
            if index is None:
                isoverlap, index = isOverlapVector(vec1[:], vec2[:])
            else:
                isoverlap = 1
            if isoverlap == 1:
                # Make sure file is up to date before copying.
                # user could have extended the file previously.
                self.sync()
                v[index:index + len(vec1)] = var.astype(v.dtype)
                vec2[index:index + len(vec1)] = vec1[:].astype(vec2[:].dtype)
                if bounds1 is not None:
                    vec2.setBounds(bounds1, persistent=1, index=index)
            else:
                raise CDMSError(
                    'Cannot write variable %s: the values of dimension %s=%s, do not overlap the ' +
                    'extended dimension %s values: %s' %
                    (varid, vec1.id, repr(
                        vec1[:]), vec2.id, repr(
                        vec2[:])))

        # pack implementation source:
        # https://www.unidata.ucar.edu/software/netcdf/docs/BestPractices.html
        if pack:
            M = var.max()
            m = var.min()
            scale_factor = (M - m) / (pow(2, n) - 2)
            add_offset = (M + m) / 2.
            v.setMissing(-pow(2, n - 1))
            scale_factor = scale_factor.astype(var.dtype)
            add_offset = add_offset.astype(var.dtype)
            tmp = (var - add_offset) / scale_factor
            tmp = numpy.round(tmp)
            tmp = tmp.astype(typ)
            v[:] = tmp.filled()
            v.scale_factor = scale_factor.astype(var.dtype)
            v.add_offset = add_offset.astype(var.dtype)
            if not hasattr(var, "valid_min"):
                v.valid_min = m.astype(var.dtype)
            if not hasattr(var, "valid_max"):
                v.valid_max = M.astype(var.dtype)
        return v

    def write_it_yourself(self, obj):
        """Tell obj to write itself to self (already open for writing), using its
           writeg method (AbstractCurveGrid has such a method, for example).

           Notes
           -----
           If `writeg` is not available, writeToFile will be used.
           If `writeToFile` is also not available, then `self.write(obj)` will be called to try to write obj as
           a variable.

           Parameters
           ----------
           obj : object containing `writeg`, `writeToFile` or `write` method.

           Returns
           -------
           Nothing is returned.
       """
        # This method was formerly called writeg and just wrote an
        # AbstractCurveGrid.
        if (hasattr(obj, 'writeg') and callable(getattr(obj, 'writeg'))):
            obj.writeg(self)
        elif (hasattr(obj, 'writeToFile') and callable(getattr(obj, 'writeToFile'))):
            obj.writeToFile(self)
        else:
            self.write(obj)

    def getVariable(self, id):
        """
        Get the variable object with the given id. Returns None if not found.

        Parameters
        ----------
        id : str id of the variable to get

        Returns
        -------
        variable  (cdms2.fvariable.FileVariable/None)

        file variable

        """
        return self.variables.get(id)

    def getVariables(self, spatial=0):
        """Get a list of variable objects.

        Parameters
        ----------
        spatial : If spatial=1 or True, only return those axes defined on latitude
                or longitude, excluding weights and bounds

        Returns
        -------
        file variable.
"""
        retval = list(self.variables.values())
        if spatial:
            retval = [x for x in retval if x.id[
                0:7] != "bounds_" and x.id[
                0:8] != "weights_" and (
                (x.getLatitude() is not None) or (
                    x.getLongitude() is not None) or (
                    x.getLevel() is not None))]
        return retval

    def getAxis(self, id):
        """Get the axis object with the given id. Returns None if not found.

        Parameters
        ----------
        id : id of the axis to get

        Returns
        --------
        file axis
        """
        return self.axes.get(id)

    def getGrid(self, id):
        """
        Get the grid object with the given id. Returns None if not found.

        Parameters
        ----------
        id : id of the grid to get

        Returns
        -------
        file axis
        """
        return self.grids.get(id)

    def getBoundsAxis(self, n, boundid=None):
        """Get a bounds axis of length n. Create the bounds axis if necessary.

        Parameters
        ----------
        n : bound id (bound_%d)

        Returns
        -------
        bounds axis
        """
        if boundid is None:
            if n == 2:
                boundid = "bound"
            else:
                boundid = "bound_%d" % n

        if boundid in self.axes:
            boundaxis = self.axes[boundid]
        else:
            boundaxis = self.createVirtualAxis(boundid, n)
        return boundaxis

    def __repr__(self):
        filerep = repr(self._file_)
        loc = filerep.find("file")
        if loc == -1:
            loc = 0
        return "<CDMS " + filerep[loc:-1] + ", status: %s>" % self._status_

# internattr.add_internal_attribute (CdmsFile, 'datapath',
# 'variables',
# 'axes',
# 'grids',
# 'xlinks',
# 'dictdict',
# 'default_variable_name',
# 'id',
# 'parent',
# 'mode')
