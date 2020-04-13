"""
Tools for solving the OBE for laser cooling
author: spe
"""
import numpy as np
import copy
import time
import numba
import scipy.sparse as sparse
from scipy.integrate import solve_ivp
from .rateeq import rateeq
from .lasers import laserBeams
<<<<<<< Updated upstream
from .common import printProgressBar
<<<<<<< Updated upstream
from .fields import magField
=======
=======
from .common import printProgressBar, spherical_dot, cart2spherical, spherical2cart
from .fields import magField
>>>>>>> Stashed changes
>>>>>>> Stashed changes

@numba.vectorize([numba.float64(numba.complex128),numba.float32(numba.complex64)])
def abs2(x):
    return x.real**2 + x.imag**2

@numba.jit(nopython=True)
def dot(A, x):
    return A @ x

@numba.jit(nopython=True)
def dot_and_add(A, x, b):
    b += A @ x


class force_profile():
    def __init__(self, R, V, num_of_beams, hamiltonian):
        if not isinstance(R, np.ndarray):
            R = np.array(R)
        if not isinstance(V, np.ndarray):
            V = np.array(V)

        if R.shape[0] != 3 or V.shape[0] != 3:
            raise TypeError('R and V must have first dimension of 3.')

        self.R = copy.copy(R)
        self.V = copy.copy(V)

        self.iterations = np.zeros(R[0].shape, dtype='int64')
        self.fq = {}
        self.f = {}
        for key in num_of_beams:
            self.fq[key] = np.zeros(R.shape + (3, num_of_beams[key]))
            self.f[key] = np.zeros(R.shape + (num_of_beams[key],))

        self.F = np.zeros(R.shape)

    def store_data(self, ind, F, F_laser, F_laser_q, iterations):
        self.iterations[ind] = iterations
        for jj in range(3):
            #self.f[(jj,) + ind] = f[jj]
            self.F[(jj,) + ind] = F[jj]
            for key in F_laser_q:
                self.f[key][(jj,) + ind] = F_laser[key][jj]
                self.fq[key][(jj,) + ind] = F_laser_q[key][jj]


class obe():
    """
    The class optical bloch equations prduces a set of optical Bloch equations
    for a given position and velocity and provides methods for
    solving them appropriately.
    """
    def __init__(self, lasers, mag_field, hamiltonian,
                 r=np.array([0., 0., 0.]), v=np.array([0., 0., 0.]),
                 mean_detuning=None, transform_into_re_im=True,
                 use_sparse_matrices=None, include_mag_forces=False):
        """
        construct_optical_bloch_eqns: this function takes in a hamiltonian, a
        set of laserBeams, and a magField function and an internal hamiltonian
        and sets up the optical bloch equations.  Arguments:
            r: position at which to evaluate the magnetic field.
            v: 3-vector velocity of the atom or molecule.
            laserBeams: a dictionary of laserBeams that say which fields drive
                which transitions in the block diagonal hamiltonian.
            magField: a function that defines the magnetic field.
            hamiltonian: the internal hamiltonian of the particle as defined by
                the hamiltonian class.
        """

        """
        There will be time-dependent and time-independent components of the optical
        Bloch equations.  The time-independent parts are related to spontaneous
        emission, applied magnetic field, and the zero-field Hamiltonian.  We
        compute the latter-two directly from the commuatator.
        """

        """
        First step is to add in the magnetic field:
        """
        self.hamiltonian = copy.copy(hamiltonian)
        self.hamiltonian.make_full_matrices()

        self.laserBeams = {} # Laser beams are meant to be dictionary,
        if isinstance(lasers, list):
            self.laserBeams['g->e'] = copy.copy(laserBeams(lasers)) # Assume label is g->e
        elif isinstance(lasers, laserBeams):
            self.laserBeams['g->e'] = copy.copy(lasers) # Again, assume label is g->e
        elif isinstance(lasers, dict):
            for key in lasers.keys():
                if not isinstance(lasers[key], laserBeams):
                    raise ValueError('Key %s in dictionary lasersBeams ' % key +
                                     'is in not of type laserBeams.')
            self.laserBeams = copy.copy(lasers) # Now, assume that everything is the same.
        else:
            raise ValueError('laserBeams is not a valid type.')

        # Check that laser beam keys and Hamiltonian keys match.
        for laser_key in self.laserBeams.keys():
            if not laser_key in self.hamiltonian.laser_keys.keys():
                raise ValueError('laserBeams dictionary keys %s ' % laser_key +
                                 'does not have a corresponding key the '+
                                 'Hamiltonian d_q.')

        if callable(mag_field):
            self.magField = magField(mag_field)
        elif isinstance(mag_field, magField):
            self.magField = copy.copy(mag_field)
        else:
            raise TypeError('mag_field must be either a lambda function or a' +
                            'magField object.')
        self.include_mag_forces = include_mag_forces

        self.transform_into_re_im = transform_into_re_im
        if use_sparse_matrices is None:
            if self.hamiltonian.n>10: # Generally offers a performance increase
                self.use_sparse_matrices = True
            else:
                self.use_sparse_matrices = False
        else:
            self.use_sparse_matrices = use_sparse_matrices

        # Make a rate equation model too:
        self.rateeq = rateeq(self.laserBeams, self.magField, hamiltonian)

        # Set up a dictionary to store any resulting force profiles.
        self.profile = {}

        # Reset the current solution to None
        self.sol = None

        # Build the matricies that control evolution:
        self.ev_mat = {}
        self.build_decay_ev()
        self.build_coherent_ev()

        # If necessary, transform the evolution matrices:
        if self.transform_into_re_im:
            self.transform_ev_matrices()

        if self.use_sparse_matrices:
            self.convert_to_sparse()

        # Finally, update the position and velocity:
        self.set_initial_position_and_velocity(r, v)


    def density_index(self, ii, jj):
        """
        This function returns the index in the rho vector that corresponds to element rho_{ij}.  If
        """
        return ii + jj*self.hamiltonian.n


    def build_coherent_ev_submatrix(self, H):
        """
        This method builds the coherent evolution based on a submatrix of the
        Hamiltonian H.  In practice, one must be careful about commutators if
        one breaks up the Hamiltonian.
        """
        ev_mat = np.zeros((self.hamiltonian.n**2, self.hamiltonian.n**2),
                               dtype='complex128')

        for ii in range(self.hamiltonian.n):
            for jj in range(self.hamiltonian.n):
                for kk in range(self.hamiltonian.n):
                    ev_mat[self.density_index(ii, jj),
                           self.density_index(ii, kk)] += 1j*H[kk, jj]
                    ev_mat[self.density_index(ii, jj),
                           self.density_index(kk, jj)] -= 1j*H[ii, kk]

        return ev_mat


    def build_coherent_ev(self):
        self.ev_mat['H0'] = self.build_coherent_ev_submatrix(
            self.hamiltonian.H_0
        )

        self.ev_mat['B'] = [None]*3
        for q in range(3):
            self.ev_mat['B'][q] = self.build_coherent_ev_submatrix(
                self.hamiltonian.mu_q[q]
            )
        self.ev_mat['B'] = np.array(self.ev_mat['B'])

        self.ev_mat['E'] = {}
        self.ev_mat['E*'] = {}
        for key in self.laserBeams.keys():
            self.ev_mat['E'][key] = [None]*3
            self.ev_mat['E*'][key] = [None]*3
            for q in range(3):
                self.ev_mat['E'][key][q] = self.build_coherent_ev_submatrix(
                    self.hamiltonian.d_q_bare[key][q]
                )
                self.ev_mat['E*'][key][q] = self.build_coherent_ev_submatrix(
                    self.hamiltonian.d_q_star[key][q]
                )
            self.ev_mat['E'][key] = np.array(self.ev_mat['E'][key])
            self.ev_mat['E*'][key] = np.array(self.ev_mat['E*'][key])


    def build_decay_ev(self):
        self.ev_mat['decay'] = np.zeros((self.hamiltonian.n**2,
                                         self.hamiltonian.n**2),
                                         dtype='complex128')

        d_q = self.hamiltonian.d_q

        # Let's first do a check of the decay rates.  We want to make sure
        # that all states in a given manifold are, in fact, decaying at the
        # same rate.
        decay_rates = np.zeros((self.hamiltonian.blocks.shape[0],))
        for ll in range(1, self.hamiltonian.blocks.shape[0]):
            this_manifold = range(sum(self.hamiltonian.ns[:ll]),
                                  sum(self.hamiltonian.ns[:ll+1]))
            # We first check to make sure the decay rate is the same for all
            # states out of the manifold.
            rates = [np.sum(np.sum(abs2(d_q[:, :ii, ii]))) for ii in this_manifold]
            rate = np.mean(rates)
            if not np.allclose(rates, rate, atol=1e-7, rtol=1e-5):
                raise ValueError('Decay rates are not equal for all states in '+
                                 'manifold #%d' % ll)
            else:
                decay_rates[ll] = rate

        # Now we start building the evolution matrices.
        # Decay into a manifold.
        for ll in range(self.hamiltonian.blocks.shape[0]-1):
            this_manifold = range(sum(self.hamiltonian.ns[:ll]),
                                  sum(self.hamiltonian.ns[:ll+1]))
            all_higher_manifolds = range(sum(self.hamiltonian.ns[:ll+1]),
                                         sum(self.hamiltonian.ns))
            for ii in this_manifold:
                for jj in this_manifold:
                    for kk in all_higher_manifolds:
                        for ll in all_higher_manifolds:
                            for q in range(3):
                                self.ev_mat['decay'][self.density_index(ii, jj),
                                                     self.density_index(kk, ll)] +=\
                                d_q[q, ii, kk]*d_q[q, ll, jj]

        # Decay out of a manifold.  Each state and coherence in the manifold
        # decays with whatever the decay rate is.  In the present case, the
        # state $i$ decays with sum(d_q[:, :ii, ii])**2.
        for ll in range(1, self.hamiltonian.blocks.shape[0]):
            this_manifold = range(sum(self.hamiltonian.ns[:ll]),
                                  sum(self.hamiltonian.ns[:ll+1]))
            for ii in this_manifold:
                for jj in this_manifold:
                    self.ev_mat['decay'][self.density_index(ii, jj),
                                         self.density_index(ii, jj)] = -decay_rates[ll]

        # Coherences decay with the average decay rate out of the manifold
        # and into the manifold.
        for ll in range(self.hamiltonian.blocks.shape[0]-1):
            for mm in range(ll+1, self.hamiltonian.blocks.shape[0]):
                this_manifold = range(sum(self.hamiltonian.ns[:ll]),
                                      sum(self.hamiltonian.ns[:ll+1]))
                other_manifold = range(sum(self.hamiltonian.ns[:mm]),
                                       sum(self.hamiltonian.ns[:mm+1]))
                for ii in this_manifold:
                    for jj in other_manifold:
                        self.ev_mat['decay'][self.density_index(ii, jj),
                                             self.density_index(ii, jj)] = \
                        -(decay_rates[ll]+decay_rates[mm])/2
                        self.ev_mat['decay'][self.density_index(jj, ii),
                                             self.density_index(jj, ii)] = \
                        -(decay_rates[ll]+decay_rates[mm])/2


    def build_transform_matrices(self):
        self.U = np.zeros((self.hamiltonian.n**2, self.hamiltonian.n**2),
                     dtype='complex128')
        self.Uinv = np.zeros((self.hamiltonian.n**2, self.hamiltonian.n**2),
                        dtype='complex128')

        for ii in range(self.hamiltonian.n):
            self.U[self.density_index(ii, ii),
                   self.density_index(ii, ii)] = 1.
            self.Uinv[self.density_index(ii, ii),
                      self.density_index(ii, ii)] = 1.

        for ii in range(self.hamiltonian.n):
            for jj in range(ii+1, self.hamiltonian.n):
                    self.U[self.density_index(ii, jj),
                           self.density_index(ii, jj)] = 1.
                    self.U[self.density_index(ii, jj),
                           self.density_index(jj, ii)] = 1j

                    self.U[self.density_index(jj, ii),
                           self.density_index(ii, jj)] = 1.
                    self.U[self.density_index(jj, ii),
                           self.density_index(jj, ii)] = -1j

        for ii in range(self.hamiltonian.n):
            for jj in range(ii+1, self.hamiltonian.n):
                    self.Uinv[self.density_index(ii, jj),
                              self.density_index(ii, jj)] = 0.5
                    self.Uinv[self.density_index(ii, jj),
                              self.density_index(jj, ii)] = 0.5

                    self.Uinv[self.density_index(jj, ii),
                              self.density_index(ii, jj)] = -0.5*1j
                    self.Uinv[self.density_index(jj, ii),
                              self.density_index(jj, ii)] = +0.5*1j


    def transform_ev_matrix(self, ev_mat):
        if not hasattr(self, 'U'):
            self.build_transform_matrices()

        ev_mat_new = self.Uinv @ ev_mat @ self.U

        # This should remove the imaginary component.
        if np.allclose(np.imag(ev_mat_new), 0):
            return np.real(ev_mat_new)
        else:
            raise ValueError('Something went dreadfully wrong.')


    def transform_ev_matrices(self):
        self.ev_mat['decay'] = self.transform_ev_matrix(self.ev_mat['decay'])
        self.ev_mat['H0'] = self.transform_ev_matrix(self.ev_mat['H0'])

        self.ev_mat['reE'] = {}
        self.ev_mat['imE'] = {}
        for key in self.ev_mat['E'].keys():
            self.ev_mat['reE'][key] = np.array([self.transform_ev_matrix(
                self.ev_mat['E'][key][jj] + self.ev_mat['E*'][key][jj]
                ) for jj in range(3)])
            self.ev_mat['imE'][key] = np.array([self.transform_ev_matrix(
                -1j*(self.ev_mat['E'][key][jj] - self.ev_mat['E*'][key][jj])
                ) for jj in range(3)])

        # Transform Bq back into Bx, By, and Bz (making it real):
        ev_mat_Bx = self.transform_ev_matrix(
            1/np.sqrt(2)*(self.ev_mat['B'][0] - self.ev_mat['B'][2])
            )
        ev_mat_By = self.transform_ev_matrix(
            1j/np.sqrt(2)*(self.ev_mat['B'][0] + self.ev_mat['B'][2])
            )
        ev_mat_Bz = self.transform_ev_matrix(
            self.ev_mat['B'][1]
            )

        del self.ev_mat['B']
        self.ev_mat['B'] = np.array([ev_mat_Bx, ev_mat_By, ev_mat_Bz])

        del self.ev_mat['E']
        del self.ev_mat['E*']

    def convert_to_sparse(self):
        def convert_based_on_shape(matrix):
            # Vector:
            if matrix.shape == (3, self.hamiltonian.n**2, self.hamiltonian.n**2):
                new_list = [None]*3
                for jj in range(3):
                    new_list[jj] = sparse.csr_matrix(matrix[jj])

                return new_list
            # Scalar:
            else:
                return sparse.csr_matrix(matrix)

        for key in self.ev_mat:
            if isinstance(self.ev_mat[key], dict):
                for subkey in self.ev_mat[key]:
                    self.ev_mat[key][subkey] = convert_based_on_shape(
                        self.ev_mat[key][subkey]
                        )
            else:
                self.ev_mat[key] = convert_based_on_shape(self.ev_mat[key])


    def set_initial_position_and_velocity(self, r0, v0):
        self.set_initial_position(r0)
        self.set_initial_velocity(v0)

    def set_initial_position(self, r0):
        self.r0 = r0
        self.sol = None

    def set_initial_velocity(self, v0):
        self.v0 = v0
        self.sol = None


    def return_magnetic_field(self, t, r):
        B = self.magField.Field(r)

        if self.transform_into_re_im:
            return B
        else:
            Bq = np.zeros((3,), dtype='complex128')

            Bq[0] = B[0]/np.sqrt(2)+1j*B[1]/np.sqrt(2)
            Bq[1] = B[2]
            Bq[2] = -B[0]/np.sqrt(2)+1j*B[1]/np.sqrt(2)

            return Bq


    def set_initial_rho(self, rho0):
        if np.any(np.isnan(rho0)) or np.any(np.isinf(rho0)):
            raise ValueError('rho0 has NaNs or Infs!')

        if self.transform_into_re_im and rho0.dtype is np.dtype('complex128'):
            self.rho0 = np.real(rho0)
        elif (not self.transform_into_re_im and
              not rho0.dtype is np.dtype('complex128')):
            self.rho0 = rho0.astype('complex128')
        else:
            self.rho0 = rho0

    def set_initial_rho_equally(self):
        if self.transform_into_re_im:
            self.rho0 = np.zeros((self.hamiltonian.n**2,))
        else:
            self.rho0 = np.zeros((self.hamiltonian.n**2,), dtype='complex128')

        for jj in range(self.hamiltonian.ns[0]):
            self.rho0[self.density_index(jj, jj)] = 1/self.hamiltonian.ns[0]

    def set_initial_rho_from_populations(self, Npop):
        if self.transform_into_re_im:
            self.rho0 = np.zeros((self.hamiltonian.n**2,))
        else:
            self.rho0 = np.zeros((self.hamiltonian.n**2,), dtype='complex128')

        if len(Npop) != self.hamiltonian.n:
            raise ValueError('Npop has only %d entries for %d states.' %
                             (len(Npop), self.hamiltonian.n))
        if np.any(np.isnan(Npop)) or np.any(np.isinf(Npop)):
            raise ValueError('Npop has NaNs or Infs!')

        Npop = Npop/np.sum(Npop) # Just make sure it is normalized.
        for jj in range(self.hamiltonian.n):
            self.rho0[self.density_index(jj, jj)] = Npop[jj]

    def set_initial_rho_from_rateeq(self):
        Neq = self.rateeq.equilibrium_populations(self.r0, self.v0, t=0)
        self.set_initial_rho_from_populations(Neq)


    def full_OBE_ev_scratch(self, r, t):
        """
        This function calculates the OBE evolution matrix at position t and r
        from scratch, first computing the full Hamiltonian, then the
        OBE evolution matrix computed via commutators, then adding in the decay
        matrix evolution.

        If Bq is None, it will compute Bq
        """
        Eq = {}
        for key in self.laserBeams.keys():
            Eq[key] = self.laserBeams[key].total_electric_field(r, t)

        Bq = self.return_magnetic_field(r, t)

        H = self.hamiltonian.return_full_H(Bq, Eq)
        ev_mat = self.build_coherent_ev_submatrix(H)

        if self.transform_into_re_im:
            return self.transform_ev_matrix(ev_mat + self.ev_mat['decay'])
        else:
            return ev_mat + self.ev_mat['decay']


    def full_OBE_ev(self, r, t):
        """
        This function calculates the OBE evolution matrix by assembling
        pre-stored versions of the component matries.  This should be
        significantly faster than full_OBE_ev_scratch, but it may suffer bugs
        in the evolution that full_OBE_ev_scratch will not.

        If Bq is None, it will compute Bq based on r, t
        """
        ev_mat = self.ev_mat['decay'] + self.ev_mat['H0']

        # Add in electric fields:
        for key in self.laserBeams.keys():
            if self.transform_into_re_im:
                Eq = self.laserBeams[key].total_electric_field(r, t)
                for ii in range(3):
                    if np.abs(Eq[ii])>1e-10:
                        ev_mat -= 0.5*np.real(Eq[ii])*self.ev_mat['reE'][key][ii]
                        ev_mat -= 0.5*np.imag(Eq[ii])*self.ev_mat['imE'][key][ii]
            else:
                Eq = self.laserBeams[key].total_electric_field(t, np.real(r))
                for ii in range(3):
                    if np.abs(Eq[ii])>1e-10:
                        ev_mat -= 0.5*np.conjugate(Eq[ii])*self.ev_mat['E'][key][ii]
                        ev_mat -= 0.5*Eq[ii]*self.ev_mat['E*'][key][ii]

        # Add in magnetic fields:
        Bq = self.return_magnetic_field(r, t)
        for ii in range(3):
            if np.abs(Bq[ii])>1e-10:
                ev_mat += Bq[ii]*self.ev_mat['B'][ii]

        return ev_mat


    def drhodt(self, r, t, rho):
        """
        It is MUCH more efficient to do matrix vector products and add the
        results together rather than to add the matrices together (as above)
        and then do the dot.  It is also most efficient to avoid doing useless
        math if the applied field is zero.
        """
        drhodt = (self.ev_mat['decay'] @ rho) + (self.ev_mat['H0'] @ rho)

        # Add in electric fields:
        for key in self.laserBeams.keys():
            if self.transform_into_re_im:
                Eq = self.laserBeams[key].total_electric_field(r, t)
                for ii in range(3):
                    if np.abs(Eq[ii])>1e-10:
                        drhodt -= 0.5*np.real(Eq[ii])*(self.ev_mat['reE'][key][ii] @ rho)
                        drhodt -= 0.5*np.imag(Eq[ii])*(self.ev_mat['imE'][key][ii] @ rho)
            else:
                Eq = self.laserBeams[key].total_electric_field(np.real(r), t)
                for ii in range(3):
                    if np.abs(Eq[ii])>1e-10:
                        drhodt -= 0.5*np.conjugate(Eq[ii])*(self.ev_mat['E'][key][ii] @ rho)
                        drhodt -= 0.5*Eq[ii]*(self.ev_mat['E*'][key][ii] @ rho)

        # Add in magnetic fields:
        Bq = self.return_magnetic_field(t, r)
        for ii in range(3):
            if np.abs(Bq[ii])>1e-10:
                drhodt += Bq[ii]*(self.ev_mat['B'][ii] @ rho)

        return drhodt


    def evolve_density(self, t_span, **kwargs):
        """
        This function evolves the optical bloch equations for some period of
        time.  Any initial velocity is kept constant while the atoms potentially
        moves through the light field.  This function is therefore useful in
        determining average forces.  It is analogous to evolve populations in
        the rateeq class.

        Any additional keyword arguments get passed to solve_ivp, which is
        what actually does the integration.
        """
        a = np.zeros((3,))

        def dydt(t, y):
            return np.concatenate((self.drhodt(y[-3:], t, y[:-6]), a, y[-6:-3]))

        self.sol = solve_ivp(dydt, t_span,
                             np.concatenate((self.rho0, self.v0, self.r0)),
                             **kwargs)


    def evolve_motion(self, t_span, **kwargs):
        """
        This function evolves the optical bloch equations for some period of
        time, with all their potential glory!
        """
        def dydt(t, y):
            return np.concatenate((self.drhodt(y[-3:], t, y[:-6]),
                                   self.force_from_rho(y[-3:], t, y[:-6]),
                                   y[-6:-3]))

        self.sol = solve_ivp(dydt, t_span,
                             np.concatenate((self.rho0, self.v0, self.r0)),
                             **kwargs)


    def expectation_value_from_sol(self, O):
        """
        Grab the expectation value from the solution of the observable O:
        """

    def force_from_rho(self, r, t, rho):
        f = np.zeros((3,))

        for key in self.laserBeams:
            # total_electric_field_gradient returns 3x3 matrix, with the form:
            # [[dE_-/dx, dE_0/dx, dE_+/dx],[dE_-/dy, dE_0/dy, dE_+/dy],
            #  [dE_-/dz, dE_0/dz, dE_+/dz]]
            if not self.transform_into_re_im:
                delE = self.laserBeams[key].total_electric_field_gradient(
                    np.real(r), t
                    )
            else:
                delE = self.laserBeams[key].total_electric_field_gradient(r, t)

            ind = self.hamiltonian.laser_keys[key]

            n = sum(self.hamiltonian.ns[:ind[0]])
            m = sum(self.hamiltonian.ns[:ind[1]])

            for ii in range(n, n+self.hamiltonian.ns[ind[0]]):
                for jj in range(m, m+self.hamiltonian.ns[ind[1]]):
                    # This array has the same shape as (t.size):
                    if self.transform_into_re_im:
                        rho_ji = rho[self.density_index(ii, jj)] -\
                                  1j*rho[self.density_index(jj, ii)]
                    else:
                        rho_ji = rho[self.density_index(jj, ii)]

                    ddotdelE = 0.5*(np.conjugate(delE[:,::-1]) @
                                    self.hamiltonian.d_q_bare[key][:, ii, jj])

                    f += 2*np.real(ddotdelE*rho_ji)

<<<<<<< Updated upstream
=======
<<<<<<< Updated upstream
=======
>>>>>>> Stashed changes
        # Are we including magnetic forces?
        if self.include_mag_forces:
            # This function returns a matrix that (3, 3) with the format:
            # [dBx/dx, dBy/dx, dBz/dx; dBx/dy, dBy/dy, dBz/dy], and so on.
            # We need to dot, and su
            delB = self.magField.gradField(r)

            # Need to reshape it to properly dot with the
<<<<<<< Updated upstream
            delBq = np.zeros(delB.shape, dtype='complex128')

            delBq[:, 0] = delB[:, 0]/np.sqrt(2)+1j*delB[:, 1]/np.sqrt(2)
            delBq[:, 1] = delB[:, 2]
            delBq[:, 2] = -delB[:, 0]/np.sqrt(2)+1j*delB[:, 1]/np.sqrt(2)
=======
            delBq = cart2pol(delB.T).T
>>>>>>> Stashed changes

            # Go through each diagonal block.
            for ll, block in enumerate(np.diag(self.hamiltonian.blocks)):
                if isinstance(block, tuple):
                    muBq = block[1].matrix
                elif isinstance(block, self.hamiltonian.vector_block):
                    muBq = block.matrix
                else:
                    muBq = None

                if not muBq is None:
                    n = sum(self.hamiltonian.ns[:ll])
                    # There must be a better way than this loop:
                    for ii in range(n, n+self.hamiltonian.ns[ll]):
                        for jj in range(n+ii, n+self.hamiltonian.ns[ll]):
                            if self.transform_into_re_im:
                                rho_ji = rho[self.density_index(ii, jj)] -\
                                          1j*rho[self.density_index(jj, ii)]
                            else:
                                rho_ji = rho[self.density_index(jj, ii)]

                            f -= 2*np.real((np.conjugate(delBq) @ muBq[:, ii-n, jj-n])*rho_ji)

<<<<<<< Updated upstream
=======
>>>>>>> Stashed changes
>>>>>>> Stashed changes
        return f

    def force_from_sol(self, return_q=False, return_laser=False):
        f = np.zeros((3, self.sol.t.shape[0]))
        f_laser_q = {}
        f_laser = {}

        if not hasattr(self, 'sol'):
            raise ValueError('No solution present to calculate force from')

        if self.transform_into_re_im:
            r = self.sol.y[-3:, :]
        else:
            r = np.real(self.sol.y[-3:, :])

        for key in self.laserBeams:
            f_laser_q[key] = np.zeros((3, 3, self.laserBeams[key].num_of_beams,
                                       self.sol.t.shape[0]))
            f_laser[key] = np.zeros((3, self.laserBeams[key].num_of_beams,
                                     self.sol.t.shape[0]))

            # Calculate rho_ji*d for this key:
            ind = self.hamiltonian.laser_keys[key]

            n = sum(self.hamiltonian.ns[:ind[0]])
            m = sum(self.hamiltonian.ns[:ind[1]])

            rho_ji_d = np.zeros((3, self.sol.t.shape[0]), dtype='complex128')

            for ii in range(n, n+self.hamiltonian.ns[ind[0]]):
                for jj in range(m, m+self.hamiltonian.ns[ind[1]]):
                    # This array has the same shape as (t.size):
                    if self.transform_into_re_im:
                        rho_ji = (self.sol.y[self.density_index(ii, jj)] -\
                                  1j*self.sol.y[self.density_index(jj, ii)])
                    else:
                        rho_ji = self.sol.y[self.density_index(jj, ii)]

                    # The first line generates an array that is (n, n, t.size).
                    # the d array is constant with time and is (n, n).
                    # We want to multiply the element by element axes (1,2) of the
                    # second array by (0, 1 of the first array.)
                    rho_ji_d += np.outer(self.hamiltonian.d_q_bare[key][:, ii, jj],
                                         rho_ji)

            if self.transform_into_re_im:
                delE = self.laserBeams[key].electric_field_gradient(
                    self.sol.y[-3:], self.sol.t
                    )
            else:
                delE = self.laserBeams[key].electric_field_gradient(
                    np.real(self.sol.y[-3:]), self.sol.t
                    )

            # Now calculate each beam independently:
            for ll, delE_laser in enumerate(delE):
                # The output array here is  (3, 3, len(laserBeams), t.size).
                # The size of delE is size  (3, 3, t.size): (kvec, pol, t)
                # The size of rho_ji_d is size  (3, t.size): (pol, t)
                f_laser_q[key][:, :, ll, :] += 2*np.real(
                    0.5*rho_ji_d.reshape(3, self.sol.t.size)*np.conjugate(delE_laser)
                    )

            f_laser[key] = np.sum(f_laser_q[key], axis=1)
            f += np.sum(f_laser[key], axis=1)

        if return_q:
            return f, f_laser, f_laser_q
        elif return_laser:
            return f, f_laser
        else:
            return f


    def find_equilibrium_force(self, **kwargs):
        deltat = kwargs.pop('deltat', 500)
        itermax = kwargs.pop('itermax', 100)
        Npts = kwargs.pop('Npts', 5001)
        rel = kwargs.pop('rel', 1e-5)
        abs = kwargs.pop('abs', 1e-9)
        debug = kwargs.pop('debug', False)

        old_f_avg = np.array([np.inf, np.inf, np.inf])

        if debug:
            print('Finding equilbrium force at '+
                  'r=(%.2f, %.2f, %.2f) ' % (self.r0[0], self.r0[1], self.r0[2]) +
                  'v=(%.2f, %.2f, %.2f) ' % (self.v0[0], self.v0[1], self.v0[2]) +
                  'with deltat = %.2f, itermax = %d, Npts = %d, ' %  (deltat, itermax, Npts) +
                  'rel = %.1e and abs = %.1e' % (rel, abs)
                  )
            self.piecewise_sols = []

        ii=0
        while ii<itermax:
            if not Npts is None:
                kwargs['t_eval'] = np.linspace(ii*deltat, (ii+1)*deltat, int(Npts))

            self.evolve_density([ii*deltat, (ii+1)*deltat], **kwargs)

            f, f_laser, f_laser_q = self.force_from_sol(return_q=True)

            f_avg = np.mean(f, axis=1)

            if debug:
                print(ii, f_avg, np.sum(f_avg**2))
                self.piecewise_sols.append(self.sol)

            if (np.sum((old_f_avg-f_avg)**2)/np.sum((f_avg)**2)<rel or
                np.sum((old_f_avg-f_avg)**2)<abs):
                break;
            else:
                old_f_avg = copy.copy(f_avg)
                self.set_initial_rho(self.sol.y[:-6, -1])
                self.set_initial_position_and_velocity(self.sol.y[-3:, -1],
                                                       self.sol.y[-6:-3, -1])
                ii+=1

        f_laser_avg = {}
        f_laser_avg_q = {}
        for key in f_laser:
            f_laser_avg[key] = np.mean(f_laser[key], axis=2)
            f_laser_avg_q[key] = np.mean(f_laser_q[key], axis=3)

        return f_avg, f_laser_avg, f_laser_avg_q, ii


    def generate_force_profile(self, R, V,  **kwargs):
        """
        Method that maps out the equilbirium forces:
        """
        name = kwargs.pop('name', None)
        progress_bar = kwargs.pop('progress_bar', False)
        deltat_r = kwargs.pop('deltat_r', None)
        deltat_v = kwargs.pop('deltat_v', None)
        deltat_tmax = kwargs.pop('deltat_tmax', np.inf)
        initial_rho = kwargs.pop('initial_rho', 'rateeq')

        if not name:
            name = '{0:d}'.format(len(self.profile))

        num_of_beams = {}
        for key in self.laserBeams:
            num_of_beams[key] = self.laserBeams[key].num_of_beams

        self.profile[name] = force_profile(R, V, num_of_beams, self.hamiltonian)

        it = np.nditer([R[0], R[1], R[2], V[0], V[1], V[2]],
                       flags=['refs_ok', 'multi_index'],
                        op_flags=[['readonly'], ['readonly'], ['readonly'],
                                  ['readonly'], ['readonly'], ['readonly']])

        if progress_bar:
            avgtime = 0.

        for (x, y, z, vx, vy, vz) in it:
            # Construct the rate equations:
            r = np.array([x, y, z])
            v = np.array([vx, vy, vz])

            if progress_bar:
                tic = time.time()

            self.set_initial_position_and_velocity(r, v)
            if initial_rho is 'rateeq':
                self.set_initial_rho_from_rateeq()
            elif initial_rho is 'equally':
                self.set_initial_rho_equally()
            else:
                raise ValueError('Argument initial_rho=%s not understood'%initial_rho)

            if deltat_v is not None:
                vabs = np.sqrt(np.sum(v**2))
                if vabs==0.:
                    kwargs['deltat'] = deltat_tmax
                else:
                    kwargs['deltat'] = np.min([2*np.pi*deltat_v/vabs, deltat_tmax])

            if deltat_r is not None:
                rabs = np.sqrt(np.sum(r**2))
                if rabs==0.:
                    kwargs['deltat'] = deltat_tmax
                else:
                    kwargs['deltat'] = np.min([2*np.pi*deltat_r/rabs, deltat_tmax])

            F, F_laser, F_laser_q, iterations = self.find_equilibrium_force(**kwargs)

            self.profile[name].store_data(it.multi_index, F, F_laser, F_laser_q,
                                          iterations)

            if progress_bar:
                toc = time.time()

                avgtime = (it.iterindex*avgtime + (toc-tic))/(it.iterindex+1.0)

                printProgressBar(it.iterindex+1, it.itersize, prefix = 'Progress:',
                                 suffix = 'complete', decimals = 1, length = 40,
                                 remaining_time = (it.itersize-it.iterindex)*avgtime)

    def reshape_sol(self):
        """
        Reshape the solution to have all the proper parts.
        """
        # This should just do it:
        rho = self.sol.y[:-6].reshape(self.hamiltonian.n, self.hamiltonian.n,
                                      self.sol.t.size)

        # If not:
        if self.transform_into_re_im:
            new_rho = np.zeros(rho.shape, dtype='complex128')
            for jj in range(new_rho.shape[2]):
                new_rho[:, :, jj] = (np.diag(np.diagonal(rho[:, :, jj])) +
                                     np.triu(rho[:, :, jj], k=1) +
                                     np.triu(rho[:, :, jj], k=1).T -
                                     1j*np.tril(rho[:, :, jj], k=-1) +
                                     1j*np.tril(rho[:, :, jj], k=-1).T)
            rho = new_rho

        return (self.sol.t, rho)
