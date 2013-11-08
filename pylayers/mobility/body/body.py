import numpy as np
import scipy.stats as sp
import ConfigParser
from pylayers.mobility.body import c3d
import pylayers.mobility.trajectory as tr
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import networkx as nx
import pdb as pdb
import pylayers.util.pyutil as pyu
import pylayers.util.plotutil as pltu
import pylayers.util.geomutil as geu
import doctest

def ChangeBasis(u0, v0, w0, v1):
    """ 

    Parameters
    ----------

    u0
    v0
    w0
    v1

    """

    # Rotate with respect to axe w

    v2 = v1 - np.dot(np.dot(v1, w0), w0)  # projection of v1 on plan (u,v)
    v2 = v2 / np.linalg.norm(v2)
    c = np.dot(v2, u0)
    s = np.dot(v2, v0)
    u1 = np.dot(s, u0) - np.dot(c, v0)
    u1 = u1 / np.linalg.norm(u1)
    w1 = np.cross(u1, v1)
    return u1, v1, w1


def dist(A, B):
    """
    evaluate the distance between two points A and B
    """

    d = np.sqrt((A[0] - B[0]) ** 2 + (A[1] - B[1]) ** 2 + (A[2] - B[2]) ** 2)
    return d


class Body(object):
    """ Class to manage the Body model 

    Methods
    -------

    load
    center
    posvel
    loadC3D
    movie
    plot3d
    geomfile
    settopos 
    setccs
    setaccs
    cylinder_basis_k
    cyl_antenna

    Notes
    -----

        nodes_Id = {0:'STRN',1:'CLAV',2:'RFHD',3:'RSHO',
        4:'LSHO', 5:'RELB',6:'LELB', 7:'RWRB',8:'LWRB', 9:'RFWT',
        10:'LFWT', 11:'RKNE', 12:'LKNE',13:'RANK',  14:'LANK' , 
        15:'LFIN' ,16:'LELB', 17:'RUPA',18:'LUPA',  19:'RFRM', 
        20:'LFRM', 21:'LSHN', 22:'RSHN',23:'LTHI',  24:'RTHI', 
        25:'LHEE', 26:'RHEE', 27:'LTOE',28:'RTOE',  29:'RMT5'}
    """

    def __init__(self,_filebody='John.ini',_filemocap='07_01.c3d'):
        di = self.load(_filebody)
        self.loadC3D(filename=_filemocap)
        self.center()

    def __repr__(self):
        st = ''
        
        if 'filename' in dir(self):
            st = st +'filename : '+ self.filename +'\n'
        if 'nframes' in dir(self):    
            st = st +'nframes : ' + str(self.nframes) +'\n'
        if 'pg' in dir(self):
            st = st + 'Centered : True'+'\n'
        if 'topos' in dir(self):
            st = st + 'topos : True'+'\n'
        else:    
            st = st + 'topos : False'+'\n'
        return(st)    


    def load(self,_filebody='John.ini'):
        """ load a body ini file

        Parameters
        ----------

        _filebody : body short filename
        
        Notes
        -----

        A body .ini file contains 4 sections

        + section [nodes]
            Node number = Node name 
        + section [cylinder]    
            Cylinder number = {'t':tail node number, 'h':head node number , 'r': cylinder' radius}
        + section [antennas]    
            Antenna number = {'cylId' cylinder Id, 'l': ,'h': parameter,'a':angle,'filename': filename}

        """
        filebody = pyu.getlong(_filebody,'ini')
        config = ConfigParser.ConfigParser()
        config.read(filebody)
        sections = config.sections()
        di = {}
        for section in sections:
            di[section] = {}
            options = config.options(section)
            for option in options:
                try:
                    if section=='nodes':
                        di[section][option] = config.get(section,option)
                    else:
                        di[section][option] = eval(config.get(section,option))
                except:
                    print section,option

        self.g = nx.Graph()
        keys = map(lambda x : eval(x),di['nodes'].keys())
        self.nodes_Id = {k:v for (k,v) in zip(keys,di['nodes'].values())}

        self.g.add_nodes_from(keys)
        for cyl in di['cylinder'].keys():
            t = di['cylinder'][cyl]['t']
            h = di['cylinder'][cyl]['h']
            r = di['cylinder'][cyl]['r']
            self.g.add_edge(t,h)
            self.g[t][h]['radius']= r 
       
        self.ant={}
        for ant in di['antenna'].keys():
            self.ant[ant]=di['antenna'][ant]

        return(di)

    def center(self):
        """ centering the body 

        Returns
        -------

        self.pg : center of gravity 
        self.d  : set of centered frames


        Notes
        -----

        Here only the projection of the body centroid in the
        plane 0xy is calculated

        """
        # self.d  : 3 x 16 x Nf
        # self.pg : 3 x Nf
        self.pg = np.sum(self.d,axis=1)/self.npoints
        self.pg[2,:] = 0
        self.d = self.d - self.pg[:,np.newaxis,:]
        # speed vector of the gravity centernp. 
        self.vg = self.pg[:,1:]-self.pg[:,0:-1] 
        # duplicate last spped vector for size homogeneity  
        #self.vg = np.hstack((self.vg,self.vg[:,-1]))
        self.vg = np.hstack((self.vg,self.vg[:,-1][:,np.newaxis]))

    def posvel(self,traj,tk,Tstep):
        """ position and velocity

        Parameters
        ----------

        traj : Tajectory DataFrame 
            nx3
        tk : float 
            time for evaluation of topos
        Tstep : flloat 
        
        Returns
        -------
        
        kf 
        kt 
        vsn : normalized speed vector along motion capture trajectory 
        wsn :  
        vtn : normalized speed vector along motion trajectory 
        wtn 

        """
        # tk should be in the trajectory time range
        assert ((tk>traj.tmin) & (tk<traj.tmax)),'posvel: tk not in trajectory time range'

        tf = Tstep/(1.0*self.nframes) # frame sampling period  
        kt = int(np.floor(tk/tf))
        kf = int(np.floor(np.mod(tk,Tstep)/tf))
        # self.pg : 3 x Nframes 
        # traj : Nptraj x 3 (t,x,y)

        # vs  : speed vector along motion capture frame
        # vsn : unitary speed vector along motion capture frame
        vs = self.pg[0:-1,kf] - self.pg[0:-1,kf-1]
        vsn = vs/np.sqrt(np.dot(vs,vs))
        wsn = np.array([vsn[1],-vsn[0]])
        #
        # vt : speed vector along trajectory 
        #
        #vt = traj[kt+1,1:] - traj[kt,1:]
        vt  = np.array([traj['vx'][kt],traj['vy'][kt]])
        vtn = vt/np.sqrt(np.dot(vt,vt))
        wtn = np.array([vtn[1],-vtn[0]])
        
        return(kf,kt,vsn,wsn,vtn,wtn)

    def settopos(self,traj,tk=0,Tstep=3):
        """ translate the body on a time stamped trajectory

        Parameters
        ----------

        traj : ndarray (3,N)
            t,x,y
        tk : float 
            time for evaluation of topos (seconds) this value should be in the
            range of the trajectory timestamp
        Tstep : float 
           duration of the periodic motion sequence (seconds)

        Examples
        --------

        >>> import numpy as np 
        >>> import pylayers.mobility.trajectory as tr  
        >>> import matplotlib.pyplot as plt
        >>> time = np.arange(0,10,0.1)
        >>> v = 4000/3600.
        >>> x = v*time
        >>> y = np.zeros(len(time))
        >>> traj = tr.Trajectory()
        >>> bc = Body()
        >>> bc.settopos(traj,2.3,2)
        >>> nx.draw(bc.g,bc.g.pos)
        >>> axe = plt.axis('scaled')
        >>> plt.show()

        Notes
        -----

        topos is the current spatial global position of a body configuration.


        See Also 
        --------

        pylayers.util.geomutil.affine

        """

        #
        #
        # psa : origin source
        # psb = psa+vsn : a point in the direction of pedestrian motion 
        #
        # pta : target translation 
        # ptb = pta+vtn : a point in the direction of trajectory 
        
        kf,kt,vsn,wsn,vtn,wtn = self.posvel(traj,tk,Tstep)

        psa = np.array([0,0])
        psb = psa + vsn
        psc = psa + wsn

        pta = np.hstack((traj['x'].values[kt],traj['y'].values[kt]))
        ptb = pta + vtn
        ptc = pta + wtn

        X   = np.array([[0,0],[psb[0],psb[1]],[psc[0],psc[1]]]).T
        Y   = np.array([[pta[0],pta[1]],[ptb[0],ptb[1]],[ptc[0],ptc[1]]]).T

        a,b = geu.affine(X,Y)

        A = np.eye(3)                
        B = np.zeros((3,1))                
        A[0:-1,0:-1] = a                
        B[0:-1,:] = b

        self.toposFrameId = kf 
        self.topos = (np.dot(A,self.d[:,:,kf])+B)
        self.vtopos = np.hstack((vtn,np.array([0])))[:,np.newaxis]
        
    
    def setaccs(self):
        """ set antenna cylinder coordinate system (accs) from a topos

        This method evaluates the set of all accs.
        It provides the information necessary for antenna placement on 
        the body. 

        If N is the number of antenna an accs  is an MDA of size 3x4xN
        
        >>> import numpy as np 
        >>> import pylayers.mobility.trajectory as tr  
        >>> import matplotlib.pyplot as plt
        >>> time = np.arange(0,10,0.1)
        >>> v = 4000/3600.
        >>> x = v*time
        >>> y = np.zeros(len(time))
        >>> traj = tr.Trajectory()
        >>> bc = Body()
        >>> bc.settopos(traj,2.3,2)
        >>> bc.setccs(topos=True)
        >>> bc.setaccs()
        >>> nx.draw(bc.g,bc.g.pos)
        >>> axe = plt.axis('scaled')
        >>> plt.show()

        """
        self.accs = {}
        for ant in self.ant.keys():

            # getting antenna placement information 

            Id = self.ant[ant]['cyl']
            alpha = self.ant[ant]['a']
            l = self.ant[ant]['l']
            h = self.ant[ant]['h']

            # getting cylinder information  

            ed = self.g.edges()[Id]
            kta = ed[0]
            khe = ed[1]
            phe = np.array(self.topos[:,khe])
            pta = np.array(self.topos[:,kta])
            dl = phe - pta 
            lmax = np.sqrt(np.dot(dl,dl))
            CCS = self.ccs[Id,:,:]
            #self.nodes_Id[kta],self.nodes_Id[khe]

            # applying rotation and translation 

            Rot = np.array([[np.cos(alpha),-np.sin(alpha),0],[np.sin(alpha),np.cos(alpha),0],[0,0,1]])
            CCSr = np.dot(CCS,Rot)
            neworigin = pta + CCSr[:,2]*l + CCSr[:,0]*h
            self.accs[ant] = np.hstack((neworigin[:,np.newaxis],CCSr))

    def loadC3D(self, filename='07_01.c3d', nframes=126 ,unit='cm'):
        """ load nframes of motion capture C3D file 

        Parameters
        ----------

        filename : string
            file name 
        nframes  : int 
            number of frames 

        """

        if 'pg' in dir(self):
            del self.pg

        self.nframes = nframes
        self.filename = filename

        s, p, f = c3d.read_c3d(filename)

        CM_TO_M = 0.01
        #
        # self.d 3 x np x nf
        # 
        self.npoints = 15
        self.d = np.ndarray(shape=(3, self.npoints, np.shape(f)[0]))
        #if self.d[2,:,:].max()>50:
        ind = []
        for i in self.nodes_Id:
            if self.nodes_Id[i]<>'BOTT':
                ind.append(p.index(s[0] + self.nodes_Id[i]))

        # f.T : 3 x np x nf
        self.d = f[0:nframes, ind, :].T
        if unit=='cm':
            self.d = self.d*CM_TO_M
        self.g.pos = {}
        for i in range(self.npoints):
            self.g.pos[i] = (self.d[1, i, 0], self.d[2, i, 0])
        #
        # Extension of cylinder
        #

        #self.g.add_node(15)
        self.npoints = 16

        pm  = (self.d[:, 9, 0] + self.d[:, 10, 0])/2.
        pmf = (self.d[:, 9, :] + self.d[:, 10, :])/2.
        pmf = pmf[:,np.newaxis,:]

        self.d = np.concatenate((self.d,pmf),axis=1)

        #self.g.add_edge(0, 15)
        self.g.pos[15] = (pm[1],pm[2])
        #self.g[0][15]['radius']=0.1
        #self.nodes_Id[15]='bottom'

    def movie(self,topos=False,tk=[],traj=[]):
        """ Create a geomview movie

        Parameters
        ----------

        topos : Boolean
        tk    : np.array time index in s 
        traj  : np.array Npt x 3 (t,x,y)    

        See Also
        --------

        Body.geomfile

        """

        if not topos:
            for k in range(self.nframes):
                self.geomfile(iframe=k,verbose=True)
        else:
            for k,ttk in enumerate(tk):
                stk = str(k).zfill(6) # for string alignement 
                self.settopos(traj=traj,tk=ttk,Tstep=1)
                self.geomfile(topos=True,verbose=False,tag=stk)

    def plot3d(self,iframe=0,topos=False,fig=[],ax=[],col='b'):
        """ scatter 3d plot 
        
        Parameters
        ----------

        iframe : int 
        topos : boolean    
        fig : 
        ax  :

        Returns
        -------
        
        fig,ax 

        """
        if fig == []:
            fig = plt.figure()
        if ax == []:
            ax = fig.add_subplot(111, projection='3d')
        if not topos:    
            ax.scatter(self.d[0, :, iframe], self.d[1, :, iframe], self.d[2, :, iframe],color=col)
        else:
            ax.scatter(self.topos[0, :], self.topos[1, :], self.topos[2, :],color=col)

        for k,e in enumerate(self.g.edges()):
            e0 = e[0]
            e1 = e[1]
            if not topos:
                pA = self.d[:,e0,iframe].reshape(3,1)
                pB = self.d[:,e1,iframe].reshape(3,1)
            else:    
                pA = self.topos[:,e0].reshape(3,1)
                pB = self.topos[:,e1].reshape(3,1)
            ax.plot(np.array([pA[0][0],pB[0][0]]),np.array([pA[1][0],pB[1][0]]),
                    np.array([pA[2][0],pB[2][0]]),zdir='z',c=col)
        #ax.auto_scale_xyz([-2,2], [-2, 1], [-2, 2])
        ax.autoscale(enable=True)
        return(fig,ax)
                    
    #def show3(self,iframe=0,topos=True,tag=''): 

    def show3(self,**kwargs): 
        """ create geomfile for frame iframe 

        Parameters
        ----------

        iframe : int 
            frame number (useless if topos == True)
        topos : boolean 
            if True shows the current body topos
        tag : aditional string for naming file .off (useless if topos==False)

        """

        defaults = { 'iframe': 0,
                    'verbose':False,
                    'topos':False,
                    'tag':'',
                    'wire':False,
                    'ccs':False,
                    'lccs':[],
                    'ccsa':False,
                    'struc':False,
                    'filestruc':'DLR.off'
                  }

        for key, value in defaults.items(): 
            if key not in kwargs: 
                kwargs[key] = value

        bdy = self.geomfile(**kwargs)
        bdy.show3()

    #def geomfile(self,iframe=0,verbose=False,topos=False,tag=''):
    def geomfile(self,**kwargs):
        """ create a geomview file from a body configuration 

        Parameters
        ----------

        iframe : int 
            frame id (useless if topos==True)
        verbose : boolean
        topos : boolean 
            frame id or topos
        wire : boolean 
            body as a wire or cylinder
        ccs : boolean
            display cylinder coordinate system
        cacs : boolean
            display cylinder antenna coordinate system
        acs : boolean
            display antenna coordinate system
        struc : boolean
            displat structure layout
        tag : string 
        filestruc : string
            name of the Layout 

        Notes
        -----

        This function creates either a 3d representation of the frame iframe
        or if topos==True a representation of the current topos. 



        """

        defaults = { 'iframe': 0,
                    'verbose':False,
                    'topos':False,
                    'tag':'',
                    'wire': False,
                    'ccs': False,
                    'lccs': [],
                    'ccsa': False,
                    'lccsa': [],
                    'struc':False,
                    'filestruc':'DLR.off'

                  }


        for key, value in defaults.items(): 
            if key not in kwargs: 
                kwargs[key] = value

        iframe = kwargs['iframe']

        if kwargs['lccs']==[]:
            lccs = np.arange(11)
        else:
            lccs = kwargs['lccs']
        
        if not kwargs['wire']:
            cyl = geu.Geomoff('cylinder')
            pt = cyl.loadpt()

        if not kwargs['topos']:
            _filebody = str(iframe).zfill(4)+'body'
        else:    
            if kwargs['tag']<>'':
                _filebody = kwargs['tag']+'-body'
            else:
                _filebody = 'body'

        bodylist = geu.Geomlist(_filebody,clear=True)
        filestruc = pyu.getlong(kwargs['filestruc'],"geom")

        bodylist.append("LIST\n")

        # add layout 
        if kwargs['struc']:
            bodylist.append('{<'+filestruc+'}\n')
        if kwargs['verbose']:
            print ("LIST\n")
        
        dbody = {}
        for k,e in enumerate(self.g.edges()):
            e0 = e[0]
            e1 = e[1]
            if not kwargs['topos']:
                pA = self.d[:,e0,iframe].reshape(3,1)
                pB = self.d[:,e1,iframe].reshape(3,1)
                vg = self.vg[:,iframe][:,np.newaxis]
            else:    
                pA = self.topos[:,e0].reshape(3,1)
                pB = self.topos[:,e1].reshape(3,1)
                vg = self.vtopos
            pM = (pA+pB)/2.
            Rcyl = self.g[e0][e1]['radius']

            if kwargs['wire']:
                dbody[k]=(pA,pB)
            else:
                # affine transformation of cylinder 
                T = geu.onb(pA,pB,vg)
                Y = np.hstack((pM,pA,pB,pM+Rcyl*T[0,:,0].reshape(3,1),
                                        pM+Rcyl*T[0,:,1].reshape(3,1),
                                        pB+Rcyl*T[0,:,0].reshape(3,1)))
                # idem geu.affine for a specific cylinder
                A,B = geu.cylmap(Y)
                ptn = np.dot(A,pt.T)+B
                if not kwargs['topos']:
                    _filename = 'edge'+str(k)+'-'+str(kwargs['iframe'])+'.off'
                else:
                    _filename = kwargs['tag']+'-edge'+str(k)+'.off'

                filename = pyu.getlong(_filename,"geom")
                cyl.savept(ptn.T,_filename)
                bodylist.append('{<'+filename+'}\n')
                if kwargs['verbose']:
                    print('{<'+filename+'}\n')
            # display selected cylinder coordinate system       
            if kwargs['ccs']:
                if k in lccs:
                    fileccs = kwargs['tag']+'ccs'+str(k)
                    geov = geu.GeomVect(fileccs)
                    pt = pA[:,0]+Rcyl*self.ccs[k,:,0]
                    geov.geomBase(self.ccs[k,:,:],pt=pt,scale=0.1)
                    bodylist.append('{<'+fileccs+'.vect'+"}\n")
            if kwargs['ccsa']:
                for key in self.accs.keys():
                    fileccsa = kwargs['tag']+'ccsa'+str(k)
                    U = self.accs[key]
                    print U
                    geoa = geu.GeomVect(fileccsa)
                    geoa.geomBase(U[:,1:],pt=U[:,0],scale=0.1)
                    bodylist.append('{<'+fileccsa+'.vect'+"}\n")
        # wireframe body             
        if kwargs['wire']:
            bodygv = geu.GeomVect('bodywire',clear=True)
            bodygv.segments(dbody,i2d=False,linewidth=5)
            bodylist.append('{<bodywire.vect}\n')

        return(bodylist)    


    def setccs(self,frameId=0,topos=False):
        """ set cylinder coordinate system 

        Parameters
        ----------

        frameId : int 
            frame id in the mocap dataframe (default 0) 
        topos : boolean     
            default True

        Returns
        -------

        self.ccs : ndarray (nc,3,3)
        
        Notes
        -----

        There are as many frame as cylinders (body graph edges) 

        """

        nc = len(self.g.edges())
        #
        # ccs : nc x 3 x 3  
        #
        self.ccs = np.ndarray(shape=(nc,3,3))

        for k,e in enumerate(self.g.edges()):
            e0 = e[0]
            e1 = e[1]
            if not topos:
                pA = self.d[:,e0,frameId].reshape(3,1)
                pB = self.d[:,e1,frameId].reshape(3,1)
                vg = self.vg[:,frameId][:,np.newaxis]
            else:    
                pA = self.topos[:,e0].reshape(3,1)
                pB = self.topos[:,e1].reshape(3,1)
                vg = self.vtopos
            pM = (pA+pB)/2.
            T = geu.onb(pA,pB,vg)
            self.ccs[k,:,:] = T 

    def cylinder_basis_k(self, frameId):
        """ 

        Parameters 
        ----------

        frameId : int  

        """
        nc = self.c.shape[0]
        self.basisk = np.ndarray(shape=(nc, 9))
        for i in range(nc):
            u0 = self.ccs[i, 0:3]
            v0 = self.ccs[i, 3:6]
            w0 = self.ccs[i, 6:]
            v1 = self.c[i, 4:7, frameId] - self.c[i, 1:4, frameId]
            v1 = v1 / np.linalg.norm(v1)
            uk, vk, wk = ChangeBasis(u0, v0, w0, v1)
            self.basisk[i, 0:3] = uk
            self.basisk[i, 3:6] = vk
            self.basisk[i, 6:] = wk

    def cyl_antenna(self, cylinderId, l, alpha, frameId=0):
        """ 
        Parameters
        ----------

        cylinderId : int 
            index of cylinder 
        l : distance from origin of cylider
        alpha : angle from reference direction 
        frameId : frameId 

        """
        r = self.c[cylinderId, 7, frameId]

        x = r * np.cos(alpha)
        y = r * np.sin(alpha)
        z = l

        if frameId == 0:
            u0 = self.ccs[cylinderId, 0:3]
            v0 = self.ccs[cylinderId, 3:6]
            w0 = self.ccs[cylinderId, 6:]

        else:
            self.cylinder_basis_k(frameId)
            u0 = self.basisk[cylinderId, 0:3]
            v0 = self.basisk[cylinderId, 3:6]
            w0 = self.basisk[cylinderId, 6:]

        self.ant = x.reshape((len(x)), 1) * u0 + \
                   y.reshape((len(y)), 1) * w0 + \
                   z.reshape((len(z)), 1) * v0


def translate(cycle, new_origin):
    """  rotate a cycle of frames by an angle alpha

    Parameters
    ----------

    cycle :  np.array
            3 x np x nf
    alpha : float
        angle in radians


    Returns
    -------

    cycle modified : np.array
        3 x np x nf
    """


    cycle_tr = np.ndarray(shape=cycle.shape)
    old_origin = cycle[:, 0, 0]
    cycle_tr = cycle + new_origin.reshape((3, 1, 1)) - \
        old_origin.reshape((3, 1, 1))

    return cycle_tr


def rotation(cycle, alpha=np.pi/2):
    """  rotate a cycle of frames by an angle alpha

    Parameters
    ----------

    cycle :  np.array
            3 x np x nf
    alpha : float
        angle in radians


    Returns
    -------

    cycle modified : np.array
        3 x np x nf
    """


    cycle_rot = np.ndarray(shape=cycle.shape)
    cycle_rot[0, :, :] = (cycle[0, :, :]) * np.cos(alpha) + (cycle[1, :, :]) * np.sin(alpha)
    cycle_rot[1, :, :] = -(cycle[0, :, :]) * np.sin(alpha) + (cycle[1, :, :]) * np.cos(alpha)
    cycle_rot[2, :, :] = cycle[2, :, :]
    cycle_rot = translate(cycle_rot, cycle[:, 0, 0])

    return cycle_rot


def Global_Trajectory(cycle, traj):
    """ 

    Parameters
    ----------

    cycle :  walking step cycle (2 step), shape = (3,npoints  = 16, nframes = 126)
    traj  : trajectory described by the gravity center, shape =(3,nposition)

    We assume that the body moves straight between two successive positions

    Returns
    -------

    data : list
        list
    """

    data = []

    fr_start_index = 0
    ref_fr = cycle[:, :, 0]
    vect_ortho = ref_fr[:, 3] - ref_fr[:, 4]
    vect_ortho = vect_ortho / np.linalg.norm(vect_ortho)
    v = np.random.random(3)
    v = v - np.dot(np.dot(v, vect_ortho), vect_ortho)
    v[2] = 0
    vect_ant = v / np.linalg.norm(v)

    for i in range(1, traj.shape[1]):

        print 'i = ', i

        vect_depl = traj.T[i] - traj.T[i - 1]
        vect_depl = vect_depl / np.linalg.norm(vect_depl)

        alpha = np.arccos(np.dot(vect_ant, vect_depl))

        cycle_i = rotation(cycle, alpha)

        dist_inter = dist(traj.T[i], traj.T[i - 1])
        Nfr = int(dist_inter * 126.0 / 140.0)
        cycle_i = translate(cycle_i, traj.T[i - 1])
        if Nfr < 126:
            if fr_start_index + Nfr < 126:
                data.append(cycle_i[:, :, fr_start_index:fr_start_index + Nfr])
                fr_start_index = fr_start_index + Nfr
            else:
                data.append(cycle_i[:, :, fr_start_index:])
                cycle_i = translate(cycle_i, cycle_i[:, 0, -1] + vect_depl)
                data.append(cycle_i[:, :, 0:fr_start_index + Nfr - 126])
                fr_start_index = fr_start_index + Nfr - 126

    return data


if __name__ == '__main__':
#    plt.ion()
#    doctest.testmod()
    bd = Body()

#    nframes = 126
#    Bc = Body()
#    Bc.loadC3D()
#    c10_1t = Bc.d
#    #nx.draw(B.g)
#    fig = plt.figure()
#
#    ax = fig.add_subplot(111, projection='3d')
#    frameID = 30
#    ax.scatter(c10_15[0, :, frameID], c10_15[1, :, frameID], c10_15[2, :, frameID])
#    ax.axis('scaled')
#
#    #ax.scatter(c10_15[frameID,:,0],c10_15[frameID,:,1],c10_15[frameID,:,2] )
#
#    pointID = 13
#
#    plt.figure()
#    plt.plot(c10_15[0, pointID].T, '*--', label='x')
#    plt.plot(c10_15[1, pointID].T, '*--', label='y')
#    plt.plot(c10_15[2, pointID].T, '*--', label='z')
#    plt.legend()
#
#    plt.show()

