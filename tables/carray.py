########################################################################
#
#       License: BSD
#       Created: June 15, 2005
#       Author:  Antonio Valentino
#       Modified by:  Francesc Altet
#
#       $Id$
#
########################################################################

"""Here is defined the CArray class.

See CArray class docstring for more info.

Classes:

    CArray

Functions:


Misc variables:

    __version__


"""

import sys, warnings

import numpy

from tables.atom import Atom, EnumAtom, split_type
from tables.leaf import Leaf
from tables.array import Array
from tables.utils import correct_byteorder


__version__ = "$Revision$"


# default version for CARRAY objects
obversion = "1.0"    # Support for time & enumerated datatypes.



class CArray(Array):
    """
    This class represents homogeneous datasets in an HDF5 file.

    The difference between a normal `Array` and a `CArray` is that a
    `CArray` has a chunked layout and, as a consequence, it supports
    compression.  You can use datasets of this class to easily save or
    load arrays to or from disk, with compression support included.

    Instance variables (specific of `CArray`):

    `atom`
        An `Atom` instance representing the shape and type of the
        atomic objects to be saved.
    `extdim`
        The *enlargeable dimension*, i.e. the dimension this array can
        be extended or shrunken along (-1 if it is not extendable).
    """

    # Class identifier.
    _c_classId = 'CARRAY'


    # Properties
    # ~~~~~~~~~~

    # Special methods
    # ~~~~~~~~~~~~~~~
    def __init__( self, parentNode, name,
                  atom=None, shape=None,
                  title="", filters=None,
                  chunkshape=None, byteorder = None,
                  _log=True ):
        """
        Create a `CArray` instance.

        Keyword arguments:

        `atom`
            An `Atom` instance representing the shape and type of the
            atomic objects to be saved.  The shape of the atom will be
            used as the chunksize of the underlying HDF5 dataset.
        `shape`
            The shape of the chunked array to be saved.
        `title`
            Sets a ``TITLE`` attribute on the array entity.
        `filters`
            An instance of the `Filters` class that provides
            information about the desired I/O filters to be applied
            during the life of this object.
        `chunkshape`
            The shape of the data chunk to be read or written in a
            single HDF5 I/O operation.  Filters are applied to those
            chunks of data.  The dimensionality of `chunkshape` must
            be the same as that of `shape`.  If ``None``, a sensible
            value is calculated (which is recommended).
        `byteorder` -- The byteorder of the data *on-disk*, specified
            as 'little' or 'big'. If this is not specified, the
            byteorder is that of the platform.
        """

        self.atom = atom
        """
        An `Atom` instance representing the shape, type of the atomic
        objects to be saved.
        """
        self.shape = None
        """The shape of the stored array."""
        self.extdim = -1  # `CArray` objects are not enlargeable by default
        """The index of the enlargeable dimension."""

        # Other private attributes
        self._v_version = None
        """The object version of this array."""
        self._v_new = new = atom is not None
        """Is this the first time the node has been created?"""
        self._v_new_title = title
        """New title for this node."""
        self._v_nrowsinbuf = None
        """The maximum number of rows that are read on each chunk iterator."""
        self._v_convert = True
        """Whether the ``Array`` object must be converted or not."""
        self._v_chunkshape = None
        """The HDF5 chunk size for ``CArray/EArray`` objects."""

        # Miscellaneous iteration rubbish.
        self._start = None
        """Starting row for the current iteration."""
        self._stop = None
        """Stopping row for the current iteration."""
        self._step = None
        """Step size for the current iteration."""
        self._nrowsread = None
        """Number of rows read up to the current state of iteration."""
        self._startb = None
        """Starting row for current buffer."""
        self._stopb = None
        """Stopping row for current buffer. """
        self._row = None
        """Current row in iterators (sentinel)."""
        self._init = False
        """Whether we are in the middle of an iteration or not (sentinel)."""
        self.listarr = None
        """Current buffer in iterators."""

        if new:
            if not isinstance(atom, Atom):
                raise ValueError, """\
atom parameter should be an instance of tables.Atom and you passed a %s.""" \
% type(atom)
            elif atom.shape != ():
                raise NotImplementedError, """\
sorry, but multidimensional atoms are not supported in this context yet."""

            if shape is None:
                raise ValueError, """\
you must specify a non-empty shape."""
            elif type(shape) not in (list, tuple):
                raise ValueError, """\
shape parameter should be either a tuple or a list and you passed a %s.""" \
% type(shape)
            self.shape = tuple(shape)

            if chunkshape is not None:
                if type(chunkshape) not in (list, tuple):
                    raise ValueError, """\
chunkshape parameter should be either a tuple or a list and you passed a %s.
""" % type(chunkshape)
                elif len(shape) != len(chunkshape):
                    raise ValueError, """\
the shape (%s) and chunkshape (%s) ranks must be equal.""" \
% (shape, chunkshape)
                elif min(chunkshape) < 1:
                    raise ValueError, """ \
chunkshape parameter cannot have zero-dimensions."""
                self._v_chunkshape = tuple(chunkshape)

        # The `Array` class is not abstract enough! :(
        super(Array, self).__init__(parentNode, name, new, filters,
                                    byteorder, _log)


    def _g_create(self):
        """Create a new array in file (specific part)."""

        # Pre-conditions
        if min(self.shape) < 1:
            raise ValueError(
                "shape parameter cannot have zero-dimensions.")
        # Finish the common part of creation process
        return self._g_create_common(self.nrows)


    def _g_create_common(self, expectedrows):
        """Create a new array in file (common part)."""

        self._v_version = obversion

        if self._v_chunkshape is None:
            # Compute the optimal chunk size
            self._v_chunkshape = self._calc_chunkshape(
                expectedrows, self.rowsize, self.atom.itemsize)
        # Compute the optimal nrowsinbuf
        self._v_nrowsinbuf = self._calc_nrowsinbuf(
            self._v_chunkshape, self.rowsize, self.atom.itemsize)
        # Correct the byteorder if needed
        if self.byteorder is None:
            self.byteorder = correct_byteorder(self.atom.type, sys.byteorder)

        try:
            # ``self._v_objectID`` needs to be set because would be
            # needed for setting attributes in some descendants later
            # on
            self._v_objectID = self._createCArray(self._v_new_title)
        except:  #XXX
            # Problems creating the Array on disk. Close node and re-raise.
            self.close(flush=0)
            raise
        return self._v_objectID


    def _g_copyWithStats(self, group, name, start, stop, step,
                         title, filters, _log):
        "Private part of Leaf.copy() for each kind of leaf"
        maindim = self.maindim
        shape = list(self.shape)
        shape[maindim] = len(xrange(start, stop, step))
        # Now, fill the new carray with values from source
        nrowsinbuf = self._v_nrowsinbuf
        # The slices parameter for self.__getitem__
        slices = [slice(0, dim, 1) for dim in self.shape]
        # This is a hack to prevent doing innecessary conversions
        # when copying buffers
        (start, stop, step) = self._processRangeRead(start, stop, step)
        self._v_convert = False
        # Build the new CArray object (do not specify the chunkshape so that
        # a sensible value would be calculated)
        object = CArray(group, name, atom=self.atom, shape=shape,
                        title=title, filters=filters, _log=_log)
        # Start the copy itself
        for start2 in range(start, stop, step*nrowsinbuf):
            # Save the records on disk
            stop2 = start2 + step * nrowsinbuf
            if stop2 > stop:
                stop2 = stop
            # Set the proper slice in the main dimension
            slices[maindim] = slice(start2, stop2, step)
            start3 = (start2-start)/step
            stop3 = start3 + nrowsinbuf
            if stop3 > shape[maindim]:
                stop3 = shape[maindim]
            # The next line should be generalised when maindim would be
            # different from 0
            object[start3:stop3] = self.__getitem__(tuple(slices))
        # Activate the conversion again (default)
        self._v_convert = True
        nbytes = numpy.product(self.shape)*self.atom.itemsize

        return (object, nbytes)