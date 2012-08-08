"""
InaSAFE Disaster risk assessment tool developed by AusAid and World Bank
- **Functionality related to shake events.**

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""
__author__ = 'tim@linfiniti.com'
__version__ = '0.5.0'
__date__ = '1/08/2012'
__copyright__ = ('Copyright 2012, Australia Indonesia Facility for '
                 'Disaster Reduction')

import os
import sys
import shutil
from xml.dom import minidom
from subprocess import (call, CalledProcessError)
import ogr
import gdal
from gdalconst import GA_ReadOnly
from utils import shakemapExtractDir

from rt_exceptions import (EventFileNotFoundError,
                           EventXmlParseError,
                           GridXmlFileNotFoundError,
                           GridXmlParseError)
# The logger is intialised in utils.py by init
import logging
LOGGER = logging.getLogger('InaSAFE-Realtime')


class ShakeEvent:
    """The ShakeEvent class encapsulates behaviour and data relating to an
    earthquake, including epicenter, magniture etc."""

    def __init__(self, theEventId):
        """Constructor for the shake event class.

        Args:
            theEventId - (Mandatory) Id of the event. Will be used to
                determine the path to an event.xml file that
                will be used to intialise the state of the ShakeEvent instance.

            e.g.

            /tmp/inasafe/realtime/shakemaps-extracted/20120726022003/event.xml

        Returns: Instance

        Raises: EventXmlParseError
        """
        self.latitude = None
        self.longitude = None
        self.eventId = theEventId
        self.magnitude = None
        self.depth = None
        self.description = None
        self.location = None
        self.day = None
        self.month = None
        self.year = None
        self.time = None
        self.timeZone = None
        self.xMinimum = None
        self.xMaximum = None
        self.yMinimum = None
        self.yMaximum = None
        self.rows = None
        self.columns = None
        self.mmiData = None
        self.parseEvent()
        self.parseGridXml()

    def eventFilePath(self):
        """A helper to retrieve the path to the event.xml file

        Args: None

        Returns: An absolute filesystem path to the event.xml file.

        Raises: EventFileNotFoundError
        """
        LOGGER.debug('Event path requested.')
        myEventPath = os.path.join(shakemapExtractDir(),
                                   self.eventId,
                                   'event.xml')
        #short circuit if the tif is already created.
        if os.path.exists(myEventPath):
            return myEventPath
        else:
            LOGGER.error('Event file not found. %s' % myEventPath)
            raise EventFileNotFoundError('%s not found' % myEventPath)

    def gridFilePath(self):
        """A helper to retrieve the path to the grid.xml file

        Args: None

        Returns: An absolute filesystem path to the grid.xml file.

        Raises: GridXmlFileNotFoundError
        """
        LOGGER.debug('Event path requested.')
        myGridXmlPath = os.path.join(shakemapExtractDir(),
                                   self.eventId,
                                   'grid.xml')
        #short circuit if the tif is already created.
        if os.path.exists(myGridXmlPath):
            return myGridXmlPath
        else:
            LOGGER.error('Event file not found. %s' % myGridXmlPath)
            raise GridXmlFileNotFoundError('%s not found' % myGridXmlPath)

    def parseEvent(self):
        """Parse the event.xml and extract whatever info we can from it.

        The event is parsed and class members are populated with whatever
        data could be obtained from the event.

        Args: None

        Returns : None

        Raises: EventXmlParseError
        """
        LOGGER.debug('ParseEvent requested.')
        myPath = self.eventFilePath()
        try:
            myDocument = minidom.parse(myPath)
            myEventElement = myDocument.getElementsByTagName('earthquake')
            myEventElement = myEventElement[0]
            self.magnitude = float(myEventElement.attributes['mag'].nodeValue)
            self.longitude = float(myEventElement.attributes['lon'].nodeValue)
            self.latitude = float(myEventElement.attributes['lat'].nodeValue)
            self.location = myEventElement.attributes[
                            'locstring'].nodeValue.strip()
            self.depth = float(myEventElement.attributes['depth'].nodeValue)
            self.year = int(myEventElement.attributes['year'].nodeValue)
            self.month = int(myEventElement.attributes['month'].nodeValue)
            self.day = int(myEventElement.attributes['day'].nodeValue)
            self.hour = int(myEventElement.attributes['hour'].nodeValue)
            self.minute = int(myEventElement.attributes['minute'].nodeValue)
            self.second = int(myEventElement.attributes['second'].nodeValue)
            # Note teh timezone here is inconsistent with YZ from grid.xml
            # use the latter
            self.timeZone = myEventElement.attributes['timezone'].nodeValue

        except Exception, e:
            LOGGER.exception('Event parse failed')
            raise EventXmlParseError('Failed to parse event file.\n%s\n%s'
                % (e.__class__, str(e)))

    def parseGridXml(self):
        """Parse the grid xyz and calculate the bounding box of the event.

        The grid xyz dataset looks like this::

           <?xml version="1.0" encoding="US-ASCII" standalone="yes"?>
           <shakemap_grid xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
           xmlns="http://earthquake.usgs.gov/eqcenter/shakemap"
           xsi:schemaLocation="http://earthquake.usgs.gov
           http://earthquake.usgs.gov/eqcenter/shakemap/xml/schemas/
           shakemap.xsd" event_id="20120807015938" shakemap_id="20120807015938"
           shakemap_version="1" code_version="3.5"
           process_timestamp="2012-08-06T18:28:37Z" shakemap_originator="us"
           map_status="RELEASED" shakemap_event_type="ACTUAL">
           <event magnitude="5.1" depth="206" lat="2.800000"
               lon="128.290000" event_timestamp="2012-08-07T01:55:12WIB"
               event_network="" event_description="Halmahera, Indonesia    " />
           <grid_specification lon_min="126.290000" lat_min="0.802000"
               lon_max="130.290000" lat_max="4.798000"
               nominal_lon_spacing="0.025000" nominal_lat_spacing="0.024975"
               nlon="161" nlat="161" />
           <grid_field index="1" name="LON" units="dd" />
           <grid_field index="2" name="LAT" units="dd" />
           <grid_field index="3" name="PGA" units="pctg" />
           <grid_field index="4" name="PGV" units="cms" />
           <grid_field index="5" name="MMI" units="intensity" />
           <grid_field index="6" name="PSA03" units="pctg" />
           <grid_field index="7" name="PSA10" units="pctg" />
           <grid_field index="8" name="PSA30" units="pctg" />
           <grid_field index="9" name="STDPGA" units="pctg" />
           <grid_field index="10" name="URAT" units="" />
           <grid_field index="11" name="SVEL" units="ms" />
           <grid_data>
           126.2900 04.7980 0.01 0.02 1.16 0.05 0.02 0 0.5 1 600
           126.3150 04.7980 0.01 0.02 1.16 0.05 0.02 0 0.5 1 600
           126.3400 04.7980 0.01 0.02 1.17 0.05 0.02 0 0.5 1 600
           126.3650 04.7980 0.01 0.02 1.17 0.05 0.02 0 0.5 1 600
           ...
           ... etc

        .. note:: We could have also obtained this data from the grid.xml
           but the **grid.xml** is preferred because it contains clear and
           unequivical metadata describing the various fields and attributes.

        We already have most of the event details from event.xml so we are
        primarily interested in event_specification (in order to compute the
        bounding box) and grid_data (in order to obtain an MMI raster).

        Args: None

        Returns: None

        Raises: GridXmlParseError
        """
        LOGGER.debug('ParseGridXml requested.')
        myPath = self.gridFilePath()
        try:
            myDocument = minidom.parse(myPath)
            mySpecificationElement = myDocument.getElementsByTagName(
                'grid_specification')
            mySpecificationElement = mySpecificationElement[0]
            self.xMinimum = float(mySpecificationElement.attributes[
                                  'lon_min'].nodeValue)
            self.xMaximum = float(mySpecificationElement.attributes[
                                  'lon_max'].nodeValue)
            self.yMinimum = float(mySpecificationElement.attributes[
                                  'lat_min'].nodeValue)
            self.yMaximum = float(mySpecificationElement.attributes[
                                  'lat_max'].nodeValue)
            self.rows = float(mySpecificationElement.attributes[
                                  'nlat'].nodeValue)
            self.columns = float(mySpecificationElement.attributes[
                                  'nlon'].nodeValue)
            myDataElement = myDocument.getElementsByTagName(
                'grid_data')
            myDataElement = myDataElement[0]
            myData = myDataElement.firstChild.nodeValue

            # Extract the 1,2 and 5th (MMI) columns and populate mmiData
            myLonColumn = 0
            myLatColumn = 1
            myMMIColumn = 4
            self.mmiData = []
            for myLine in myData.split('\n'):
                if not myLine:
                    continue
                myTokens = myLine.split(' ')
                myLon = myTokens[myLonColumn]
                myLat = myTokens[myLatColumn]
                myMMI = myTokens[myMMIColumn]
                myTuple= (myLon, myLat, myMMI)
                self.mmiData.append(myTuple)

        except Exception, e:
            LOGGER.exception('Event parse failed')
            raise GridXmlParseError('Failed to parse grid file.\n%s\n%s'
                % (e.__class__, str(e)))

    def mmiDataToDelimitedText(self):
        """Return the mmi data as a delimited test string.

        The returned string will look like this::

           123.0750,01.7900,1
           123.1000,01.7900,1.14
           123.1250,01.7900,1.15
           123.1500,01.7900,1.16
           etc...

        Args: None

        Returns: str - a delimited text string that can easily be written to
            disk for e.g. use by gdal_grid.

        Raises: None

        """
        myString = 'lon,lat,mmi\n'
        for myRow in self.mmiData:
            myString += '%s,%s,%s\n' % (myRow[0], myRow[1], myRow[2])
        return myString

    def mmiDataToDelimitedFile(self, theForceFlag=True):
        """Save the mmiData to a delimited text file suitable for processing
        with gdal_grid.

        The output file will be of the same format as strings returned from
        :func:`mmiDataToDelimitedText`.

        .. note:: An accompanying .csvt will be created which gdal uses to
           determine field types. The csvt will contain the following string:
           "Real","Real","Real". These types will be used in other conversion
           operations. For example to convert the csv to a shp you would do::

              ogr2ogr -select mmi -a_srs EPSG:4326 mmi.shp mmi.vrt mmi

        Args: theForceFlag bool (Optional). Whether to force the regeneration
            of the output file. Defaults to False.

        Returns: str The absolute file system path to the delimited text
            file.

        Raises: None
        """
        LOGGER.debug('mmiDataToDelimitedText requested.')

        myPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi.csv')
        #short circuit if the csv is already created.
        if os.path.exists(myPath) and theForceFlag is not True:
            return myPath
        myFile = file(myPath,'wt')
        myFile.write(self.mmiDataToDelimitedText())
        myFile.close()

        # Also write the .csvt which contains metadata about field types
        myCsvtPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi.csvt')
        myFile = file(myCsvtPath,'wt')
        myFile.write('"Real","Real","Real"')
        myFile.close()
        return myPath

    def mmiDataToVrt(self, theForceFlag=True):
        """Save the mmiData to an ogr vrt text file.

        Args: theForceFlag bool (Optional). Whether to force the regeneration
            of the output file. Defaults to False.

        Returns: str The absolute file system path to the .vrt text file.

        Raises: None
        """
        # Ensure the delimited mmi file exists
        LOGGER.debug('mmiDataToVrt requested.')

        myVrtPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi.vrt')

        #short circuit if the vrt is already created.
        if os.path.exists(myVrtPath) and theForceFlag is not True:
            return myVrtPath

        myCsvPath = self.mmiDataToDelimitedFile(theForceFlag)

        myVrtString = ('<OGRVRTDataSource>'
                       '  <OGRVRTLayer name="mmi">'
                       '    <SrcDataSource>%s</SrcDataSource>'
                       '    <GeometryType>wkbPoint</GeometryType>'
                       '    <GeometryField encoding="PointFromColumns"'
                       '                      x="lon" y="lat" z="mmi"/>'
                       '  </OGRVRTLayer>'
                       '</OGRVRTDataSource>' % myCsvPath)
        myFile = file(myVrtPath, 'wt')
        myFile.write(myVrtString)
        myFile.close()
        return myVrtPath

    def _addExecutablePrefix(self, theCommand):
        """Add the executable prefix for gdal binaries.

        This is primarily needed for OSX where gdal tools are tucked away in
        the Library path.

        Args: theCommand str - Required. A string containing the command to
            which the prefix will be prepended.

        Returns: str - A copy of the command with the prefix added.

        Raises: None
        """

        myExecutablePrefix = ''
        if sys.platform == 'darwin':  # Mac OS X
            # .. todo:: FIXME - softcode gdal version in this path
            myExecutablePrefix = ('/Library/Frameworks/GDAL.framework/'
                                  'Versions/1.9/Programs/')
        theCommand = myExecutablePrefix + theCommand
        return theCommand

    def _runCommand(self, theCommand):
        """Run a command and raise any error as needed.

        This is a simple runner for executing gdal commands.

        Args: theCommand str - Required. A command string to be run.

        Returns: None

        Raises: Any exceptions will be propogated.
        """

        myCommand = self._addExecutablePrefix(theCommand)

        try:
            myResult = call(theCommand, shell=True)
            del myResult
        except CalledProcessError, e:
            myMessage = ('Error while executing the following shell '
                           'command: %\nError message: %s'
                         % (theCommand, str(e)))
            # shameless hack - see https://github.com/AIFDR/inasafe/issues/141
            if sys.platform == 'darwin':  # Mac OS X
                if 'Errno 4' in str(e):
                    # continue as the error seems to be non critical
                    pass
                else:
                    raise Exception(myMessage)
            else:
                raise Exception(myMessage)

    def mmiDataToShapefile(self, theForceFlag=False):
        """Convert the grid.xml's mmi column to a vector shp file using ogr2ogr.

        An ESRI shape file will be created.

        Example of the ogr2ogr call we generate::

           ogr2ogr -select mmi -a_srs EPSG:4326 mmi.shp mmi.vrt mmi

        .. note:: It is assumed that ogr2ogr is in your path.

        Args: theForceFlag bool (Optional). Whether to force the regeneration
            of the output file. Defaults to False.

        Return: str Path to the resulting tif file.

        Raises: None
        """
        LOGGER.debug('mmiDataToShapefile requested.')

        myShpPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi-points.shp')
        # Short circuit if the tif is already created.
        if os.path.exists(myShpPath) and theForceFlag is not True:
            return myShpPath

        # Ensure the vrt mmi file exists (it will generate csv too if needed)
        myVrtPath = self.mmiDataToVrt(theForceFlag)

        #now generate the tif using default interpoation options

        myCommand = (('ogr2ogr -overwrite -select mmi -a_srs EPSG:4326 '
                      '%(shp)s %(vrt)s mmi') % {
                        'shp': myShpPath,
                        'vrt': myVrtPath
                     })


        LOGGER.info('Created this gdal command:\n%s' % myCommand)
        # Now run GDAL warp scottie...
        self._runCommand(myCommand)

        # Lastly copy over the standard qml (QGIS Style file) for the mmi.tif
        myQmlPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi-points.qml')
        mySourceQml = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
            'fixtures',
            'mmi-shape.qml'))
        shutil.copyfile(mySourceQml, myQmlPath)
        return myShpPath

    def mmiDataToRaster(self, theForceFlag=False):
        """Convert the grid.xml's mmi column to a raster using gdal_grid.

        A geotiff file will be created.

        Unfortunately no python bindings exist for doing this so we are
        going to do it using a shell call.

        .. seealso:: http://www.gdal.org/gdal_grid.html

        Example of the gdal_grid call we generate::

           gdal_grid -zfield "mmi" -a invdist:power=2.0:smoothing=1.0 \
           -txe 126.29 130.29 -tye 0.802 4.798 -outsize 400 400 -of GTiff \
           -ot Float16 -l mmi mmi.vrt mmi.tif

        .. note:: It is assumed that gdal_grid is in your path.

        Args: theForceFlag bool (Optional). Whether to force the regeneration
            of the output file. Defaults to False.

        Return: str Path to the resulting tif file.

        Raises: None
        """
        LOGGER.debug('mmiDataToRaster requested.')

        myTifPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi.tif')
        #short circuit if the tif is already created.
        if os.path.exists(myTifPath) and theForceFlag is not True:
            return myTifPath

        # Ensure the vrt mmi file exists (it will generate csv too if needed)
        myVrtPath = self.mmiDataToVrt(theForceFlag)

        # now generate the tif using default nearest neighbour interpoation
        # options. This gives us the same output as the mi.grd generated by
        # the earthquake server.

        myCommand = (('gdal_grid -a nearest -zfield "mmi" -txe %(xMin)s '
                      '%(xMax)s -tye %(yMin)s %(yMax)s -outsize %(dimX)i '
                      '%(dimX)i -of GTiff -ot Float16 -a_srs EPSG:4326 -l mmi '
                      '%(vrt)s %(tif)s') % {
                        'xMin': self.xMinimum,
                        'xMax': self.xMaximum,
                        'yMin': self.yMinimum,
                        'yMax': self.yMaximum,
                        'dimX': self.columns,
                        'dimY': self.rows,
                        'vrt': myVrtPath,
                        'tif': myTifPath
                     })

        LOGGER.info('Created this gdal command:\n%s' % myCommand)
        # Now run GDAL warp scottie...
        self._runCommand(myCommand)

        # Lastly copy over the standard qml (QGIS Style file) for the mmi.tif
        myQmlPath = os.path.join(shakemapExtractDir(),
                              self.eventId,
                              'mmi.qml')
        mySourceQml = os.path.abspath(
            os.path.join(os.path.dirname(__file__),
            'fixtures',
            'mmi.qml'))
        shutil.copyfile(mySourceQml, myQmlPath)
        return myTifPath


    def mmiDataToContours(self, theForceFlag=True):
        """Extract contours from the event's tif file.

        Contours are extracted at a 1MMI interval. The resulting file will
        be saved in gisDataDir(). In the easiest use case you can simply do::

           myShakeEvent = myShakeData.shakeEvent()
           myContourPath = myShakeEvent.mmiToContours()

        which will return the contour dataset for the latest event on the
        ftp server.

        Args: theForceFlag - (Optional). Whether to force the regeneration
            of contour product. Defaults to False.

        Returns: An absolute filesystem path pointing to the generated
            contour dataset.

        Raises: ContourCreationError

        """
        LOGGER.debug('mmiDataToContours requested.')
        # TODO: Use sqlite rather?
        myOutputFileBase = os.path.join(shakemapExtractDir(),
                                        self.eventId,
                                        'mmi_contours.')
        myOutputFile = myOutputFileBase + 'shp'
        if os.path.exists(myOutputFile) and theForceFlag is not True:
            return myOutputFile
        elif os.path.exists(myOutputFile):
            os.remove(myOutputFileBase + 'shp')
            os.remove(myOutputFileBase + 'shx')
            os.remove(myOutputFileBase + 'dbf')
            os.remove(myOutputFileBase + 'prj')

        myTifPath = self.mmiDataToRaster(theForceFlag)
        # Based largely on
        # http://svn.osgeo.org/gdal/trunk/autotest/alg/contour.py
        myDriver = ogr.GetDriverByName('ESRI Shapefile')
        myOgrDataset = myDriver.CreateDataSource(myOutputFile)
        if myOgrDataset is None:
            # Probably the file existed and could not be overriden
            raise ContourCreationError('Could not create datasource for:\n%s'
                'Check that the file does not already exist and that you '
                'do not have file system permissions issues')
        myLayer = myOgrDataset.CreateLayer('contour')
        myFieldDefinition = ogr.FieldDefn('ID', ogr.OFTInteger)
        myLayer.CreateField(myFieldDefinition)
        myFieldDefinition = ogr.FieldDefn('MMI', ogr.OFTReal)
        myLayer.CreateField(myFieldDefinition)
        myTifDataset = gdal.Open(myTifPath, GA_ReadOnly)
        # see http://gdal.org/java/org/gdal/gdal/gdal.html for these options
        myBand = 1
        myContourInterval = 1  # MMI not M!
        myContourBase = 0
        myFixedLevelList = []
        myUseNoDataFlag = 0
        myNoDataValue = -9999
        myIdField = 0  # first field defined above
        myElevationField = 1  # second (MMI) field defined above

        gdal.ContourGenerate(myTifDataset.GetRasterBand(myBand),
                             myContourInterval,
                             myContourBase,
                             myFixedLevelList,
                             myUseNoDataFlag,
                             myNoDataValue,
                             myLayer,
                             myIdField,
                             myElevationField)
        del myTifDataset
        myOgrDataset.Release()
        return myOutputFile

    def __str__(self):
        """The unicode representation for an event object's state.

        Args: None

        Returns: str A string describing the ShakeEvent instance

        Raises: None
        """
        if self.mmiData:
          mmiData = 'Populated'
        else:
          mmiData = 'Not populated'
        myString = (('latitude: %(latitude)s\n'
                     'longitude: %(longitude)s\n'
                     'eventId: %(eventId)s\n'
                     'magnitude: %(magnitude)s\n'
                     'depth: %(depth)s\n'
                     'description: %(description)s\n'
                     'location: %(location)s\n'
                     'day: %(day)s\n'
                     'month: %(month)s\n'
                     'year: %(year)s\n'
                     'time: %(time)s\n'
                     'timeZone: %(timeZone)s\n'
                     'xMinimum: %(xMinimum)s\n'
                     'xMaximum: %(xMaximum)s\n'
                     'yMinimum: %(yMinimum)s\n'
                     'yMaximum: %(yMaximum)s\n'
                     'rows: %(rows)s\n'
                     'columns: %(columns)s\n'
                     'mmiData: %(mmiData)s') %
                     {
                       'latitude': self.latitude,
                       'longitude': self.longitude,
                       'eventId': self.eventId,
                       'magnitude': self.magnitude,
                       'depth': self.depth,
                       'description': self.description,
                       'location': self.location,
                       'day': self.day,
                       'month': self.month,
                       'year': self.year,
                       'time': self.time,
                       'timeZone': self.timeZone,
                       'xMinimum': self.xMinimum,
                       'xMaximum': self.xMaximum,
                       'yMinimum': self.yMinimum,
                       'yMaximum': self.yMaximum,
                       'rows': self.rows,
                       'columns': self.columns,
                       'mmiData': mmiData
                     })
        return myString


