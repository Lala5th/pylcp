import numpy as np
from .common import spherical2cart

# Next, define a Hamiltonian class to work out the internal states:
class hamiltonian():
    """
    A representation of the Hamiltonian in blocks

    Diagonal blocks describe the internal structure of a manifold, and
    off-diagonal blocks describe how those manifolds are connected via laser
    Beams and the associated dipole matrix elements.  For most cases, the
    Hamiltonian is usually just a two level system.  In this case, the
    Hamiltonian can be initiated using the optional parameters below and the
    two manifolds are given the labels :math:`g` and :math:`e`.  You must
    supply the five positional arguments below in order to initiate the
    Hamiltonian in this way.

    For other constructions with more than two manifolds, one should construct
    the Hamiltonian using the `pylcp.hamiltonian.add_H_0_block()`,
    `pylcp.hamiltonian.add_mu_q_block()` and `pylcp.hamiltonian.add_d_q_block()`.
    Note that the order in which the diagonal blocks are added is the energy
    ordering of the manifolds, which is often obscured after the rotating
    wave approximation is taken (and implicitly assumed to be taken before
    construction of this Hamiltonian object).

    For more information, see the accompanying paper that describes the
    block nature of the Hamiltonian.

    Parameters
    ----------
    H0_g : array_like, shape (N, N), optional
        Ground manifold field-independent matrix
    H0_e : array_like, shape (M, M), optional
        Excited manifold field-independent matrix
    muq_g : array_like, shape (3, N, N), optional
        Ground manifold magnetic field-dependent component, in spherical basis.
    muq_e : array_like, shape (3, M, M), optional
        Excited manifold magnetic field-dependent component, in spherical basis.
    d_q : array_like, shape (3, N, M), optional
        Dipole operator that connects the ground and excited manifolds, in
        spherical basis.
    mass : float
        Mass of the atom or molecule
    muB : Bohr magneton
        Value of the Bohr magneton in the units of choice
    gamma : float
        Value of the decay rate associated with :math:`d_q`
    k : float
        Value of the wavevector associated with :math:`d_q`

    Attributes
    ----------
    ns : int
        Total number of states in the Hamiltonian
    state_labels : list of char
        Updated list of the state labels used in the Hamiltonian.
    laser_keys : dict
        The laser keys dictionary translates laser pumping keys like `g->e` into
        block indices for properly extracting the associated :math:`d_q` matrix.
    """
    class block():
        def __init__(self, label, M):
            self.label = label
            self.diagonal = self.check_diagonality(M)
            self.matrix = M
            self.parameters = {}

            self.n = M.shape[0]
            self.m = M.shape[1]

        def check_diagonality(self, M):
            if M.shape[0] == M.shape[1]:
                return np.count_nonzero(M - np.diag(np.diagonal(M))) == 0
            else:
                return False # Cannot be diagonal, cause not square.

        def return_block_in_place(self, i, j, N):
            super_M = np.zeros((N, N), dtype='complex128')
            super_M[i:i+self.n, j:j+self.m] = self.matrix

            return super_M

        def __repr__(self):
            return '(%s %dx%d)' % (self.label, self.n, self.m)

        def __str__(self):
            return '(%s %dx%d)' % (self.label, self.n, self.m)


    class vector_block(block):
        def __init__(self, label, M):
            super().__init__(label, M)

            self.n = M.shape[1]
            self.m = M.shape[2]

        def check_diagonality(self, M):
            if M.shape[1] == M.shape[2]:
                return np.count_nonzero(M[1] - np.diag(np.diagonal(M[1]))) == 0
            else:
                return False # Cannot be diagonal, cause not square.

        def return_block_in_place(self, i, j, N):
            super_M = np.zeros((3, N, N), dtype='complex128')
            super_M[:, i:i+self.n, j:j+self.m] = self.matrix

            return super_M


    def __init__(self, *args, mass=1., muB=1, gamma=1., k=1):
        self.blocks = []
        self.state_labels = []
        self.ns = []
        self.laser_keys = {}
        self.mass = mass

        if len(args) == 5:
            self.add_H_0_block('g', args[0])
            self.add_H_0_block('e', args[1])
            self.add_mu_q_block('g', args[2], muB=muB)
            self.add_mu_q_block('e', args[3], muB=muB)

            self.add_d_q_block('g', 'e', args[4], gamma=gamma, k=k)
        elif len(args)>2:
            raise ValueError('Unknown nummber of arguments.')
        elif len(args)>0:
            raise NotImplementedError('Not yet programmed for %d arguments.' %
                                      len(args))

    def print_structure(self):
        """
        Print structure of the Hamiltonian
        """
        print(self.blocks)

    def set_mass(self, mass):
        """
        Sets the Hamiltonian's mass parameter

        Parameters
        ----------
        mass : float
            The mass of the atom or molecule of the Hamiltonian
        """
        self.mass=mass

    def __recompute_number_of_states(self):
        self.n = 0
        for block in np.diag(self.blocks):
            if isinstance(block, tuple):
                self.n += block[0].n
            else:
                self.n += block.n

    def __search_elem_label(self, label):
        ind = ()
        for ii, row in enumerate(self.blocks):
            for jj, element in enumerate(row):
                if isinstance(element, self.block):
                    if element.label == label:
                        ind = (ii, jj)
                        break;
                elif isinstance(element, tuple):
                    if np.any([element_i.label == label for element_i in element]):
                        ind = (ii, jj)
                        break;

        return ind

    def __make_elem_label(self, type, state_label):
        if type == 'H_0' or type == 'mu_q':
            if not isinstance(state_label, str):
                raise TypeError('For type %s, state label %s must be a' +
                                ' string.' % (type,state_label))
            return '<%s|%s|%s>' % (state_label, type, state_label)
        elif type == 'd_q':
            if not isinstance(state_label, list):
                raise TypeError('For type %s, state label %s must be a' +
                                ' list of two strings.' % (type, state_label))
            return '<%s|%s|%s>' % (state_label[0], type, state_label[1])
        else:
            raise ValueError('Matrix element type %s not understood' % type)


    def __add_new_row_and_column(self):
        if len(self.blocks) == 0:
            self.blocks = np.empty((1,1), dtype=object)
        else:
            blocks = np.empty((self.blocks.shape[0]+1,
                               self.blocks.shape[1]+1), dtype=object)
            blocks[:-1, :-1] = self.blocks
            self.blocks = blocks


    def add_H_0_block(self, state_label, H_0):
        """
        Adds a new H_0 block to the hamiltonian

        Parameters
        ----------
        state_label : str
            Label for the manifold for which this new block applies
        H_0 : array_like, with shape (N, N)
            Square matrix that describes the field-independent part of this
            manifold's Hamiltonian.  This manifold must have N states.
        """
        if H_0.shape[0] != H_0.shape[1]:
            raise ValueError('H_0 must be square.')

        ind_H_0 = self.__search_elem_label(self.__make_elem_label('H_0', state_label))
        ind_mu_q = self.__search_elem_label(self.__make_elem_label('mu_q', state_label))

        label = self.__make_elem_label('H_0', state_label)
        if not ind_H_0 and not ind_mu_q:
            self.__add_new_row_and_column()
            self.blocks[-1, -1] = self.block(label, H_0.astype('complex128'))
            self.state_labels.append(state_label)
            self.ns.append(H_0.shape[0])
        elif ind_mu_q:
            if H_0.shape[0] != self.blocks[ind_H_0].n:
                raise ValueError('Element %s is not the right shape to match mu_q.' % label)
            self.blocks[ind_mu_q] = (self.block(label, H_0.astype('complex128')),
                                     self.blocks[ind_mu_q])
        else:
            raise ValueError('H_0 already added.')

        self.__recompute_number_of_states()
        self.__check_diagonal_submatrices_are_themselves_diagonal()


    def add_mu_q_block(self, state_label, mu_q, muB=1):
        """
        Adds a new $\mu_q$ block to the hamiltonian

        Parameters
        ----------
        state_label : str
            Label for the manifold for which this new block applies
        mu_q : array_like, with shape (3, N, N)
            Square matrix that describes the magnetic field dependent part of
            this manifold's Hamiltonian.
        """
        if mu_q.shape[0] != 3 or mu_q.shape[1] != mu_q.shape[2]:
            raise ValueError('mu_q must 3xnxn, where n is an integer.')

        ind_H_0 = self.__search_elem_label(self.__make_elem_label('H_0', state_label))
        ind_mu_q = self.__search_elem_label(self.__make_elem_label('mu_q', state_label))

        label = self.__make_elem_label('mu_q', state_label)
        new_block = self.vector_block(label, mu_q.astype('complex128'))
        new_block.parameters['mu_B'] = muB

        if not ind_H_0 and not ind_mu_q:
            self.__add_new_row_and_column()
            self.blocks[-1, -1] = new_block
            self.state_labels.append(state_label)
            self.ns.append(mu_q.shape[1])
        elif ind_H_0:
            if mu_q.shape[1] != self.blocks[ind_H_0].n:
                raise ValueError('Element %s is not the right shape to match H_0.' % label)
            self.blocks[ind_H_0] = (self.blocks[ind_H_0], new_block)
        else:
            raise ValueError('mu_q already added.')

        self.__recompute_number_of_states()
        self.__check_diagonal_submatrices_are_themselves_diagonal()


    def add_d_q_block(self, label1, label2, d_q, k=1, gamma=1):
        """
        Adds a new :math:`d_q` block to the hamiltonian to connect two
        manifolds together.

        Parameters
        ----------
        label1 : str
            Label for the first manifold to which this block applies
        label2 : str
            Label for the second manifold to which this block applies
        d_q : array_like, with shape (3, N, M)
            Matrix that describes the electric field dependent part of
            this dipole matrix element.  The first manifold must
        k : float, optional
            The mangitude of the k-vector for this $d_q$ block.  Default: 1
        gamma : float, optional
            The mangitude of the decay rate associated with this $d_q$ block.
            Default: 1
        """
        ind_H_0 = self.__search_elem_label(self.__make_elem_label('H_0', label1))
        ind_mu_q = self.__search_elem_label(self.__make_elem_label('mu_q', label1))

        if ind_H_0 == () and ind_mu_q == ():
            raise ValueError('Label %s not found.' % label1)
        elif ind_H_0 == ():
            ind1 = ind_mu_q[0]
            n = self.blocks[ind_mu_q].n
        elif ind_mu_q == ():
            ind1 = ind_H_0[0]
            n = self.blocks[ind_H_0].n
        else:
            ind1 = ind_H_0[0]
            n = self.blocks[ind_H_0][0].n

        ind_H_0 = self.__search_elem_label(self.__make_elem_label('H_0', label2))
        ind_mu_q = self.__search_elem_label(self.__make_elem_label('mu_q', label2))

        if ind_H_0 == () and ind_mu_q == ():
            raise ValueError('Label %s not found.' % label1)
        elif ind_H_0 == ():
            ind2 = ind_mu_q[0]
            m = self.blocks[ind_mu_q].n
        elif ind_mu_q == ():
            ind2 = ind_H_0[0]
            m = self.blocks[ind_H_0].n
        else:
            ind2 = ind_H_0[0]
            m = self.blocks[ind_H_0][0].n

        # Check the size of d_q, make sure it is right:
        if d_q.shape[1]!=n or d_q.shape[2]!=m:
            raise ValueError('Expected size 3x%dx%d for %s, instead see 3x%dx%d'%
                             (n, m, label, d_q.shape[1], d_q.shape[2]))

        # what is the block index to store this d_q?
        ind = (ind1, ind2)

        # If we were given d_q^\dagger, flip it around
        if ind1>ind2:
            (label1, label2) = (label2, label1)
            ind = ind[::-1]
            d_q = np.einsum("ijk->ikj",d_q.conj())

        # Store the matrix d_q:
        label = self.__make_elem_label('d_q', [label1, label2])
        self.blocks[ind] = self.vector_block(label, d_q.astype('complex128'))
        self.blocks[ind].parameters['k'] = k
        self.blocks[ind].parameters['gamma'] = gamma

        # Store the matrix d_q^\dagger
        label = self.__make_elem_label('d_q', [label2, label1])
        self.blocks[ind[::-1]] = self.vector_block(
            label,
            np.array([np.conjugate(d_q[ii].T) for ii in range(3)]).astype('complex128')
            )

        # Store the laser key for quick access:
        self.laser_keys[label1 + '->' + label2] = ind


    def make_full_matrices(self):
        """
        Returns the full matrices that define the Hamiltonian.

        Assembles the full Hamiltonian matrices from the stored block
        representation, and returns the Hamiltonian in the appropriate parts.
        For this function, :math:`n` is the number of states

        Returns
        -------
        H_0 : array_like, shape (n, n)
            The diagonal portion of the Hamiltonian
        mu_q : array_like, shape (3, N, N)
            The magnetic field dependent portion, in spherical basis.
        d_q : dictionary of array_like, shape (3, N, N)
            The electric field dependent portion, in spherical basis, arranged
            by keys that describe the manifolds connected by the specific
            :math:`d_q`.  This usually gets paired with :math:`E^*`
        d_q_star : dictionary of array_like, shape (3, N, N)
            The electric field dependent portion, in spherical basis, arranged
            by keys that describe the manifolds connected by the specific
            :math:`d_q`.  This usually gets paired with :math:`E`
        """
        # Initialize the field-independent component of the Hamiltonian.
        self.H_0 = np.zeros((self.n, self.n), dtype='complex128')
        self.mu_q = np.zeros((3, self.n, self.n), dtype='complex128')

        n = 0
        m = 0

        # First, return H_0 and mu_q:
        for diag_block in np.diag(self.blocks):
            if isinstance(diag_block, self.vector_block):
                self.mu_q += (diag_block.parameters['mu_B']*
                              diag_block.return_block_in_place(n, n, self.n))
                n+=diag_block.n
            elif isinstance(diag_block, self.block):
                self.H_0 += diag_block.return_block_in_place(n, n, self.n)
                n+=diag_block.n
            else:
                self.H_0 += diag_block[0].return_block_in_place(n, n, self.n)
                self.mu_q += (diag_block[1].parameters['mu_B']*
                              diag_block[1].return_block_in_place(n, n, self.n))
                n+=diag_block[0].n

        self.d_q_bare = {}

        # Next, return d_q:
        for ii in range(self.blocks.shape[0]):
            for jj in range(ii+1, self.blocks.shape[1]):
                if not self.blocks[ii, jj] is None:
                    key = self.state_labels[ii] + '->' + self.state_labels[jj]
                    nstart = int(np.sum(self.ns[:ii]))
                    mstart = int(np.sum(self.ns[:jj]))
                    self.d_q_bare[key] = self.blocks[ii, jj].return_block_in_place(nstart, mstart, self.n)

        self.d_q_star = {}
        for key in self.d_q_bare.keys():
            self.d_q_star[key] = np.zeros(self.d_q_bare[key].shape, dtype='complex128')
            for kk in range(3):
                self.d_q_star[key][kk] = np.conjugate(self.d_q_bare[key][kk].T)

        # Finally, put together the full d_q, irrespective of laser beam key:
        self.d_q = np.zeros((3, self.n, self.n), dtype='complex128')
        for key in self.d_q_bare.keys():
            self.d_q += self.d_q_bare[key] + self.d_q_star[key]

        # Make Cartesian coordinate copies.
        self.mu = spherical2cart(self.mu_q)
        self.d = spherical2cart(self.d_q)

        return self.H_0, self.mu_q, self.d_q_bare, self.d_q_star


    def return_full_H(self, Eq, Bq):
        """
        Assemble the block diagonal Hamiltonian into a single matrix

        Parameters
        ----------
        Eq : array_like or dictionary of array_like
            The electric field(s) driving transitions between manifolds,
            each expressed in the spherical basis.  Each electric field
            driving a transition between manifolds needs to specified with the
            correct key in the dictionary.  For example, for a two-manifold
            Hamiltonian with manifold labels `g` and `e`, the dictionary should
            contain a single entry with `g->e`.  If the electric field is
            given as a single array_like, it is assumed to drive the `g->e`
            transition.
        Bq : array_like, shape (3,)
            The magnetic field in spherical basis.

        Returns
        -------
        H : array_like
            The full Hamiltonian matrix
        """
        if not hasattr(self, 'H_0'):
            self.make_full_matrices()

        H = self.H_0 - np.tensordot(self.mu_q, np.conjugate(Bq), axes=(0, 0))

        if isinstance(Eq, list) or isinstance(Eq, np.ndarray):
            Eq = {'g->e':Eq} # Promote to a dictionary.

        for key in Eq.keys():
            for ii, q in enumerate(np.arange(-1., 2., 1.)):
                H -= (0.5*(-1.)**q*self.d_q_bare[key][ii]*Eq[key][2-ii] +
                      0.5*(-1.)**q*self.d_q_star[key][ii]*np.conjugate(Eq[key][2-ii]))

        return H


    def __check_diagonal_submatrices_are_themselves_diagonal(self):
        self.diagonal = np.zeros((self.blocks.shape[0],), dtype='bool')

        for ii, diag_block in enumerate(np.diag(self.blocks)):
            if isinstance(diag_block, tuple):
                self.diagonal[ii] = (diag_block[0].diagonal and diag_block[1].diagonal)
            else:
                self.diagonal[ii] = diag_block.diagonal


    def diag_static_field(self, B):
        """
        Block diagonalize at a specified magnetic field

        This function diagonalizes the Hamiltonian's diagonal blocks separately
        based on the value of the static magnetic field :math:`B`, and then
        rotates the :math:`d_q`s into the new bases. This is necessary for the
        rate equations, which always assume that :\math:`B` sets the quantization
        axis, and they rotate the coordinate system appropriately, so we only
        ever need to consider the z-component of the field.

        Parameters
        ----------
        B : float
            The magnetic field value at which to diagonalize.  It is always
            assumed to be along the :math:`\hat{z}` direction.

        Returns:
        H : pylcp.hamiltonian
            A block-structured Hamiltonian with diagonal elemented diagonalized
            and :math:`d_q` objects rotated
        """
        # Now we get to the meat of it:
        if not (isinstance(B, float) or isinstance(B, int)):
            raise ValueError('diag_static_field: the field should be given '+
                             'by a single number, the magnitude (assumed '+
                             'to be along z).')

        # If it does not already exist, make an empty Hamiltonian that has
        # the same dimensions as this one.
        if not hasattr(self, 'rotated_hamiltonian'):
            self.rotated_hamiltonian = hamiltonian()
            for ii, block in enumerate(np.diagonal(self.blocks)):
                self.rotated_hamiltonian.add_H_0_block(
                    self.state_labels[ii],
                    np.zeros((self.ns[ii], self.ns[ii]), dtype='complex128')
                    )
            for ii, block_row in enumerate(self.blocks):
                for jj, block in enumerate(block_row):
                    if jj>ii:
                        if not block is None:
                            self.rotated_hamiltonian.add_d_q_block(
                                self.state_labels[ii], self.state_labels[jj],
                                block.matrix,
                                )

        # Have we previously generated a set of transformation matrices?
        if not hasattr(self, 'U'):
            self.U = np.empty((self.blocks.shape[0],), dtype=object)
            # Now, go through all of the diagonal elements:
            for ii, diag_block in enumerate(np.diag(self.blocks)):
                # Make a transformation matrix that is boring.  We'll overwrite
                # it later if it gets interesting.
                self.U[ii] = np.eye(self.ns[ii])

        # Now, are any of the diagonal submatrices not diagonal?
        if not np.all(self.diagonal) or B<0:
            # If so, go through all of the diagonal elements:
            for ii, diag_block in enumerate(np.diag(self.blocks)):
                # It isn't? Diagonalize it:
                if not self.diagonal[ii] or B<0:
                    if isinstance(diag_block, tuple):
                        H = (diag_block[0].matrix - B*diag_block[1].matrix[1])
                    elif isinstance(diag_block, self.vector_block):
                        H = -B*diag_block.matrix[1]
                    else:
                        H = diag_block.matrix

                    # Diagonalize at this field:
                    Es, self.U[ii] = np.linalg.eig(H)

                    # Sort the  output, store the transformation matrix.
                    ind_e = np.argsort(Es)
                    Es = Es[ind_e]
                    self.U[ii] = self.U[ii][:, ind_e]

                    # Check to make sure the diganolization resulted in only real
                    # components, then build the matrix with the eigenvalues and
                    # go
                    if np.allclose(np.imag(Es), 0.):
                        self.rotated_hamiltonian.blocks[ii, ii].matrix = np.diag(np.real(Es))
                    else:
                        raise ValueError('You broke the Hamiltonian!')
                else: # It is diagonal:
                    if isinstance(diag_block, tuple):
                        self.rotated_hamiltonian.blocks[ii, ii].matrix = \
                            diag_block[0].matrix - B*diag_block[1].matrix[1]
                    elif isinstance(diag_block, self.vector_block):
                        self.rotated_hamiltonian.blocks[ii, ii].matrix = \
                            -B*diag_block.matrix[1]
                    else:
                        self.rotated_hamiltonian.blocks[ii, ii].matrix = \
                            diag_block.matrix

            # Now, rotate the d_q:
            for ii in range(self.blocks.shape[0]):
                for jj in range(ii+1, self.blocks.shape[1]):
                    if (not self.blocks[ii, jj] is None) and (not self.diagonal[ii] or not self.diagonal[jj] or B<0):
                        for kk in range(3):
                            self.rotated_hamiltonian.blocks[ii, jj].matrix[kk] = \
                                self.U[ii].T @ self.blocks[ii,jj].matrix[kk] @ self.U[jj]

                            self.rotated_hamiltonian.blocks[jj, ii].matrix[kk] = \
                                np.conjugate(self.rotated_hamiltonian.blocks[ii, jj].matrix[kk].T)

                            if (self.rotated_hamiltonian.blocks[ii, jj].matrix.shape !=
                                self.blocks[ii,jj].matrix.shape):
                                raise ValueError("Rotataed d_q not the same size as original.")
        else:
            # We are already diagonal, so all we have to do is change the
            # eigenvalues.
            for ii, diag_block in enumerate(np.diag(self.blocks)):
                if isinstance(diag_block, tuple):
                    self.rotated_hamiltonian.blocks[ii, ii].matrix = \
                        np.real(diag_block[0].matrix - B*diag_block[1].matrix[1])
                elif isinstance(diag_block, self.vector_block):
                    self.rotated_hamiltonian.blocks[ii, ii].matrix = \
                        np.real(-B*diag_block.matrix[1])
                else:
                    self.rotated_hamiltonian.blocks[ii, ii].matrix = \
                        np.real(diag_block.matrix)

        return self.rotated_hamiltonian


    def diag_H_0(self, B0):
        pass


# %%
if __name__ == '__main__':
    """
    A simple test of the Hamiltonian class.
    """
    Hg, mugq = hamiltonians.singleF(F=1, muB=1)
    He, mueq = hamiltonians.singleF(F=2, muB=1)
    d_q = pylcp.hamiltonians.dqij_two_bare_hyperfine(1, 2)

    ham1 = hamiltonian()
    ham1.add_H_0_block('g', Hg)
    ham1.add_mu_q_block('g', mugq)
    print(ham1.blocks)
    ham1.add_H_0_block('e', He)
    ham1.add_mu_q_block('e', mueq)
    print(ham1.blocks)
    ham1.add_d_q_block('g', 'e', d_q)
    print(ham1.blocks)

    ham1.make_full_matrices()
    ham1.diag_static_field(np.array([0, 0.5, 0]))
