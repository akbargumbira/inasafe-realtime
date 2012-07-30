"""
InaSAFE Disaster risk assessment tool developed by AusAid and World Bank
- **Tests Shake Data functionality related to shakemaps.**

Contact : ole.moller.nielsen@gmail.com

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'tim@linfiniti.com'
__version__ = '0.5.0'
__date__ = '30/07/2012'
__copyright__ = ('Copyright 2012, Australia Indonesia Facility for '
                 'Disaster Reduction')

import unittest
from shake_data import ShakeData


class TestShakeMap(unittest.TestCase):
    """Testing for the shakemap class"""
    def test_getShakeMapInput(self):
        """Check that we can retrieve a shakemap 'inp' input file"""
        myShakeEvent = '20110413170148'
        myShakeData = ShakeData(myShakeEvent)
        myShakemapFile =  myShakeData.fetchInput()
        myExpectedFile = os.path.join(DATA_DIR, myShakeEvent + 'inp.zip')
        myMessage = 'Expected path for downloaded shakemap not received'
        self.assertEqual(myShakemapFile, myExpectedFile, myMessage)

    def test_getShakeMapOutput(self):
        """Check that we can retrieve a shakemap 'out' input file"""
        myShakeEvent = '20110413170148'
        myShakeData = ShakeData(myShakeEvent)
        myShakemapFile =  myShakeData.fetchOutput()
        myExpectedFile = os.path.join(DATA_DIR, myShakeEvent + 'out.zip')
        myMessage = 'Expected path for downloaded shakemap not received'
        self.assertEqual(myShakemapFile, myExpectedFile, myMessage)

    def test_getShakeMap(self):
        """Check that we can retrieve both input and output from ftp at once"""
        myShakeEvent = '20110413170148'
        myShakeData = ShakeData(myShakeEvent)
        myInpFile, myOutFile =  myShakeData.fetch()
        myExpectedInpFile = os.path.join(DATA_DIR, myShakeEvent + 'inp.zip')
        myExpectedOutFile = os.path.join(DATA_DIR, myShakeEvent + 'out.zip')
        myMessage = 'Expected path for downloaded shakemap INP not received'
        self.assertEqual(myInpFile, myExpectedInpFile, myMessage)
        myMessage = 'Expected path for downloaded shakemap OUT not received'
        self.assertEqual(myOutFile, myExpectedOutFile, myMessage)

    def test_getLatestShakeMap(self):
        """Check that we can retrieve the latest shake event"""
        myShakeEvent = '20110413170148'
        myShakeData = ShakeData(myShakeEvent)
        myInpFile, myOutFile =  myShakeData.fetchLatest()
        myExpectedInpFile = os.path.join(DATA_DIR, myShakeEvent + 'inp.zip')
        myExpectedOutFile = os.path.join(DATA_DIR, myShakeEvent + 'out.zip')
        myMessage = 'Expected path for downloaded shakemap INP not received'
        self.assertEqual(myInpFile, myExpectedInpFile, myMessage)
        myMessage = 'Expected path for downloaded shakemap OUT not received'
        self.assertEqual(myOutFile, myExpectedOutFile, myMessage)

if __name__ == '__main__':
    unittest.main()
