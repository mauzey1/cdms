# Forecast support, experimental coding
# probably all this will be rewritten, put in a different directory, etc.

"""CDMS Forecast"""


from __future__ import print_function
import numpy
import cdtime
import cdms2
import copy
from cdms2 import CDMSError
from six import string_types


def two_times_from_one(t):
    """
    Two Times from One

    Parameters
    ----------
    Input : is a time representation, either as the long int used in the
            cdscan script, or a string in the format "2010-08-25 15:26:00", or
            as a cdtime comptime (component time) object.

    Output : is the same time, both as a long _and_ as a comptime.
    """
    if t == 0:
        t = 0
    if isinstance(t, string_types):
        t = cdtime.s2c(t)
    if (isinstance(t, int) or isinstance(t, int)) and t > 1000000000:
        tl = t
        year = tl // 1000000000
        rem = tl % 1000000000
        month = rem // 10000000
        rem = rem % 10000000
        day = rem // 100000
        allsecs = rem % 100000
        sec = allsecs % 60
        allmins = allsecs // 60
        min = allmins % 60
        hour = allmins // 60
        tc = cdtime.comptime(year, month, day, hour, min, sec)
    else:
        # I'd like to check that t is type comptime, but although Python
        # prints the type as <type 'comptime'> it won't recognize as a type
        # comptime or anything similar.  Note that cdtime.comptime is a C
        # function available from Python.
        tc = t
        tl = tc.year * 1000000000
        tl += tc.month * 10000000
        tl += tc.day * 100000
        tl += tc.hour * 3600
        tl += tc.minute * 60
        tl += tc.second.__int__()
    return tl, tc


def comptime(t):
    """
    Comptime

    Parameters
    ----------

    Input : is a time representation, either as the long int used in the cdscan
            script, or a string in the format "2010-08-25 15:26:00", or as a cdtime comptime
            (component time) object.
    Output : is the same time a cdtime.comptime (component time)."""
    tl, tc = two_times_from_one(t)
    return tc


class forecast():
    """
    represents a forecast starting at a single time

    Parameters
    ----------

    tau0time : is the first time of the forecast, i.e. the time at which tau=0.

    dataset_list : is used to get the forecast file from the forecast time.

    Example
    -------
       Each list item should look like this example:
       [None, None, None, None, 2006022200000L, 'file2006-02-22-00000.nc']
       Normally dataset_list = fm[i][1] where fm is the output of
       cdms2.dataset.parseFileMap and fm[i][0] matches the variables of interest.

    Notes
    -----
       N.B.  This is like a CdmsFile.  Creating a forecast means opening a file,
       so later on you should call forecast.close() to close it.
    """

    def __init__(self, tau0time, dataset_list, path="."):
        """

        """
        self.fctl, self.fct = two_times_from_one(tau0time)

        filenames = [l[5] for l in dataset_list if l[4] == self.fctl]
        if len(filenames) > 0:
            filename = filenames[0]
        else:
            raise CDMSError("Cannot find filename for forecast %d" % self.fctl)
        self.filename = path + '/' + filename
        self.file = cdms2.open(self.filename)

    def close(self):
        """close file."""
        self.file.close()

    def __call__(self, varname):
        """Reads the specified variable from this forecast's file."""
        return self.file(varname)

    def __getitem__(self, varname):
        """Reads variable attributes from this forecast's file."""
        return self.file.__getitem__(varname)

    def __repr__(self):
        return "<forecast from %s>" % (self.fct)
    __str__ = __repr__


def available_forecasts(dataset_file, path="."):
    """
    Available Forecasts

    Returns
    -------
          a list of forecasts (as their generating times) which are available
          through the specified cdscan-generated dataset xml file.

    Note
         The forecasts are given in 64-bit integer format, but can be converted
         to component times with the function two_times_from_one.
         This function may help in choosing the right arguments for initializing
         a "forecasts" (forecast set) object.
    """
    dataset = cdms2.openDataset(dataset_file, dpath=path)
    fm = cdms2.dataset.parseFileMap(dataset.cdms_filemap)
    alltimesl = [f[4] for f in fm[0][1]]  # 64-bit (long) integers
    dataset.close()
    return alltimesl


class forecasts():
    """
    Represents a set of forecasts

    Example
    -------
    Creates a set of forecasts.  Normally you do it by something like

    f = forecasts( 'file.xml', (min_time, max_time) )
             or
    f = forecasts( 'file.xml', (min_time, max_time), '/home/me/data/' )
             or
    f = forecasts( 'file.xml', [ time1, time2, time3, time4, time5 ] )

    where the two or three arguments are::

       1. the name of a dataset xml file generated by "cdscan --forecast ..."

       2. Times here are the times when the forecasts began (tau=0, aka reference time).

          (i) If you use a 2-item tuple, forecasts will be chosen which start at a time
          t between the min and max times, e.g. min_time <= t < max_time .

          (ii) If you use a list, it will be the exact start (tau=0) times for the
          forecasts to be included.

          (iii) If you use a 3-item tuple, the first items are (min_time,max_time)
          as in a 2-item tuple.  The third component of the tuple is the
          open-closed string.  This determines whether endpoints are included
          The first character should be 'o' or 'c' depending on whether you want t with
          min_time<t or min_time<=t.  Similarly the second character should be 'o' or c'
          for t<max_time or t<=max_time .  Any other characters will be ignored.
          Thus ( min_time, max_time, 'co' ) is equivalent to ( min_time, max_time ).

          (iv) The string 'All' means to use all available forecasts.

           Times can be specified either as 13-digit long integers, e.g.
           2006012300000 for the first second of January 23, 2006, or as
           component times (comptime) in the cdtime module, or as
           a string in the format "2010-08-25 15:26:00".

       3. An optional path for the data files; use this if the xml file
          contains filenames without complete paths.

          As for the forecast class, this opens files when initiated, so when you
          are finished with the forecasts, you should close the files by calling
          forecasts.close() .
        """

    def __init__(self, dataset_file, forecast_times, path="."):
        """
        Init
        """

        # Create dataset_list to get a forecast file from each forecast time.
        self.dataset = cdms2.openDataset(dataset_file, dpath=path)
        fm = cdms2.dataset.parseFileMap(self.dataset.cdms_filemap)
        self.alltimesl = [f[4] for f in fm[0][1]]  # 64-bit (long) integers
        dataset_list = fm[0][1]
        for f in fm[1:]:
            dataset_list.extend(f[1])

        mytimesl = self.forecast_times_to_list(forecast_times)
        if mytimesl == []:
            raise CDMSError(
                "bad forecast_times argument to forecasts.__init__")
        self.fcs = [forecast(t, dataset_list, path) for t in mytimesl]

    def forecast_times_to_list(self, forecast_times):
        """For internal list, translates a "forecast_times" argument of __init__ or
        other methods, into a list of times."""
        if isinstance(forecast_times, tuple):
            if len(forecast_times) <= 2:
                openclosed = 'co'
            else:
                openclosed = forecast_times[2]
            mytimesl = self.time_interval_to_list(
                forecast_times[0], forecast_times[1], openclosed)
            return mytimesl
        elif isinstance(forecast_times, list):
            return forecast_times
        elif forecast_times == 'All':
            return self.alltimesl
        else:
            return []

    def time_interval_to_list(self, tlo, thi, openclosed='co'):
        """For internal use, translates a time interval to a list of times.
        """
        if not isinstance(tlo, int):  # make tlo a long integer
            tlo, tdummy = two_times_from_one(tlo)
        if not isinstance(thi, int):  # make thi a long integer
            thi, tdummy = two_times_from_one(thi)
        oclo = openclosed[0]
        ochi = openclosed[1]
        if oclo == 'c':
            mytimesl = [t for t in self.alltimesl if t >= tlo]
        else:
            mytimesl = [t for t in self.alltimesl if t > tlo]
        if ochi == 'c':
            mytimesl = [t for t in mytimesl if t <= thi]
        else:
            mytimesl = [t for t in mytimesl if t < thi]
        return mytimesl

    def reduce_inplace(self, min_time, max_time, openclosed='co'):
        """
        Reduce Inplace

        Example

        For a forecasts object f, f( min_time, max_time ) will reduce the
        scope of f, to forecasts whose start time t has min_time<=t<max_time.
        This is done in place, i.e. any other forecasts in f will be discarded.
        If slice notation were possible for forecasts (it's not because we need
        too many bits to represent time), this function would do the same as
        f = f[min_time : max_time ]

        The optional openclosed argument lets you specify the treatment of
        the endpoints min_time, max_time.  The first character should be 'c' if you want
        to include min_time in the new scope of f, or 'o' to exclude it.  Similarly,
        the second character should be 'c' to include max_time or 'o' to exclude it.  Thus
        'co' yields the default min_time<=t<max_time and 'oo' yields min_time<t<max_time.

        If you don't want to change the original "forecasts" object, just do
        copy.copy(forecasts) first.

        Times can be the usual long integers, strings, or cdtime component times.
        """
        mytimesl = self.time_interval_to_list(min_time, max_time, openclosed)
        self.fcs = [f for f in self.fcs if (f.fctl in mytimesl)]

    def close(self):
        self.dataset.close()
        for fc in self.fcs:
            fc.close()

    def __call__(self, varname, forecast_times='All'):
        """

        Example

        Reads the specified variable for all the specified forecasts.
        Creates and returns a new variable which is dimensioned by forecast
        as well as the original variable's dimensions.
        Normally all the forecasts in the 'forecasts' object will be read.
        But you can read only the forecasts generated at particular times
        by providing a "forecast_times" argument, the same as the "forecast_times"
        argument in the forecasts.__init__ method.
        """
        # Assumptions include: For two forecasts, f1('var') and f2('var') are
        # the same variable in all but values - same names, same domain,
        # same units, same mask, etc.
        # Note 1: Why can't we start out by doing self.dataset(varname) as in
        # __getitem__?  That's simpler to code, but in this case it would require
        # reading large amounts of data from files, only to throw it away.
        # Note 2: if you want slices, e.g. in space axes, this isn't the
        # function for you.  Invoke __getitem__ to get a DatasetVariable,
        # then do your slicing on that.

        # Generate the forecast list, and read in the variable for every
        # listed forecast.
        if forecast_times == 'All':
            varfcs = self.fcs
        else:
            mytimesl = self.forecast_times_to_list(forecast_times)
            varfcs = [f for f in self.fcs if (f.fctl in mytimesl)]
        vars = [fc(varname) for fc in varfcs]

        # Create the variable from the data, with mask:
        v0 = vars[0]
        a = numpy.asarray([v.data for v in vars])
        if (isinstance(v0._mask, numpy.ndarray)):
            m = numpy.asarray([v._mask for v in vars])
            v = cdms2.tvariable.TransientVariable(
                a, mask=m, fill_value=v0._fill_value)
        else:
            m = False
            v = cdms2.tvariable.TransientVariable(a)

        # Domain-related attributes:
            # We get the tomain from __getitem__ to make sure that fcs[var] is consistent
            # with fcs(var)
        fvd = self.__getitem__(varname, varfcs).domain
        v._TransientVariable__domain = fvd
        # former domain code, not using __getitem:
        # ltvd = len(v0._TransientVariable__domain)
        # v._TransientVariable__domain[1:ltvd+1] = v0._TransientVariable__domain[0:ltvd]
        # v._TransientVariable__domain[0] = self.forecast_axis( varname, varfcs )
        if hasattr(v0, 'coordinates'):
            v.coordinates = 'iforecast ' + v0.coordinates

        # Other attributes, all those for which I've seen nontrivial values in a
        # real example (btw, the _isfield one was wrong!) :
        # It would be better to do a list comprehension over v0.attribures.keys(),
        # if I could be sure that that wouldn't transfer something
        # inappropriate.
        if hasattr(v0, 'id'):
            v.id = v0.id
        if hasattr(v0, 'long_name'):
            v.long_name = v0.long_name
        if hasattr(v0, 'standard_name'):
            v.standard_name = v0.standard_name
        if hasattr(v0, 'base_name'):
            v.base_name = v0.base_name
        if hasattr(v0, 'units'):
            v.units = v0.units
        if hasattr(v0, '_isfield'):
            v._isfield = v0._isfield
        return v

    def forecast_axis(self, varname, fcss=None):
        """
        Forecast Axis

        Returns
        -------

         a tuple (axis,start,length,true_length) where axis is in the forecast direction.

        Notes
        -----
        If a list of forecasts be specified, the axis' data will be limited to them."""
        if fcss is None:
            fcss = self.fcs
        axis = None
        domitem1 = None
        domitem2 = None
        domitem3 = None

        var = self.dataset[varname]
        # ... var is a DatasetVariable, used here just for two of its domain's axes
        dom = copy.deepcopy(getattr(var, 'domain', []))
        # ...this 'domain' attribute has an element with an axis, etc.
        # representing all forecasts; so we want to cut it down to match
        # those forecasts in fcss.
        for domitem in dom:
            # The domain will have several directions, e.g. forecast, level, latitude.
            # There should be only one forecast case, whose default id is 'fctau0'.
            # domitem is a tuple (axis,start,length,true_length) where
            # axis is a axis.Axis and the rest of the tuple is int's.
            # I don't know what true_length is, but it doesn't seem to get used
            # anywhere, and is normally the same as length.
            if getattr(domitem[0], 'id', None) == 'fctau0':
                # Force the axis to match fcss :
                # More precisely the long int times fcss[i].fctl should match
                # the axis data. The axis partition and .length need changing
                # too.
                domitem1 = 0
                domitem2 = len(fcss)
                domitem3 = len(fcss)
                axis = copy.copy(domitem[0])
                axis._data_ = [f.fctl for f in fcss]
                axis.length = len(axis._data_)
                axis.partition = axis.partition[0:axis.length]
                axis.axis = 'F'
                axis.standard_name = 'forecast_reference_time'
                timeaxis = var.getTime()
                if not hasattr(axis, 'calendar') and timeaxis:
                    axis.calendar = timeaxis.calendar

        return (axis, domitem1, domitem2, domitem3)

    def __getitem__(self, varname, fccs=None):
        """
        Get Item

        Returns
        -------

        whatever the forecast set has that matches the given attribute, normally a DatasetVariable.


        Notes
        -----

       The optional argument fccs is a list of forecasts to be passed on to forecast_axis().
        """
        if not isinstance(varname, string_types):
            raise CDMSError("bad argument to forecasts[]")

        var = self.dataset[varname]
        # var is a DatasetVariable and consists of lots of attributes.

        # The attribute which needs to be changed is 'domain' - it will normally
        # have an element with an axis, etc. representing all forecasts; so we
        # want to cut it down to match those forecasts in self.fcs.
        dom = copy.deepcopy(getattr(var, 'domain', []))
        for i in range(len(dom)):
            domitem = dom[i]
            if getattr(domitem[0], 'id', None) == 'fctau0':
                dom[i] = self.forecast_axis(varname, fccs)
        setattr(var, 'domain', dom)

        return var

    def __repr__(self):
        nlength = len(self.fcs)
        if nlength == 0:
            return "<forecasts - None>"
        else:
            return "<forecasts from %s,...,%s>" % (
                self.fcs[0].fct, self.fcs[nlength - 1].fct)
    __str__ = __repr__
