from cython.parallel import parallel, prange
from libcpp.vector cimport vector
from libcpp.string cimport string
import numpy as np
cimport numpy as np
from libcpp cimport bool


cdef extern from "ViZDoom.h" namespace "vizdoom":
    enum ScreenResolution:
        pass

    enum ScreenFormat:
        CRCGCB = 0  # 3 channels of 8-bit values in RGB order
        CRCGCBDB = 1  # 4 channels of 8-bit values in RGB + depth buffer order
        RGB24 = 2  # channel of RGB values stored in 24 bits where R value is stored in the oldest 8 bits
        RGBA32 = 3  # channel of RGBA values stored in 32 bits where R value is stored in the oldest 8 bits
        ARGB32 = 4  # channel of ARGB values stored in 32 bits where A value is stored in the oldest 8 bits
        CBCGCR = 5  # 3 channels of 8-bit values in BGR order
        CBCGCRDB = 6  # 4 channels of 8-bit values in BGR + depth buffer order
        BGR24 = 7  # channel of BGR values stored in 24 bits where B value is stored in the oldest 8 bits
        BGRA32 = 8  # channel of BGRA values stored in 32 bits where B value is stored in the oldest 8 bits
        ABGR32 = 9  # channel of ABGR values stored in 32 bits where A value is stored in the oldest 8 bits
        GRAY8 = 10  # 8-bit gray channel
        DEPTH_BUFFER8 = 11  # 8-bit depth buffer channel
        DOOM_256_COLORS8 = 12

    enum Button:
        pass

    enum Mode:
        pass

    enum GameVariable:
        KILLCOUNT = 0
        ITEMCOUNT = 1
        SECRETCOUNT = 2
        FRAGCOUNT = 3
        DEATHCOUNT = 4
        HEALTH = 5
        ARMOR = 6
        DEAD = 7
        ON_GROUND = 8
        ATTACK_READY = 9
        ALTATTACK_READY = 10
        SELECTED_WEAPON = 11
        SELECTED_WEAPON_AMMO = 12
        AMMO0 = 13
        AMMO1 = 14
        AMMO2 = 15
        AMMO3 = 16
        AMMO4 = 17
        AMMO5 = 18
        AMMO6 = 19
        AMMO7 = 20
        AMMO8 = 21
        AMMO9 = 22
        WEAPON0 = 23
        WEAPON1 = 24
        WEAPON2 = 25
        WEAPON3 = 26
        WEAPON4 = 27
        WEAPON5 = 28
        WEAPON6 = 29
        WEAPON7 = 30
        WEAPON8 = 31
        WEAPON9 = 32
        USER1 = 33
        USER2 = 34
        USER3 = 35
        USER4 = 36
        USER5 = 37
        USER6 = 38
        USER7 = 39
        USER8 = 40
        USER9 = 41
        USER12 = 44
        USER13 = 45
        USER14 = 46
        USER15 = 47
        USER16 = 48
        USER17 = 49
        USER18 = 50
        USER19 = 51
        USER20 = 52
        USER21 = 53
        USER22 = 54
        USER23 = 55
        USER24 = 56
        USER25 = 57
        USER26 = 58
        USER27 = 59
        USER28 = 60
        USER29 = 61
        USER30 = 62


    cppclass DoomGame:

        DoomGame() nogil

        void close() nogil

        void setViZDoomPath(string path) nogil

        void setDoomGamePath(string path) nogil

        void setDoomScenarioPath(string path) nogil

        void setDoomMap(string path) nogil

        string getDoomMap() nogil

        void setScreenResolution(ScreenResolution resolution) nogil

        void setScreenFormat(ScreenFormat format) nogil

        void setRenderHud(bool hud) nogil

        void setRenderCrosshair(bool crosshair) nogil

        void setRenderWeapon(bool weapon) nogil

        void setRenderDecals(bool decals) nogil

        void setRenderParticles(bool particles) nogil

        void setLivingReward(double livingReward) nogil

        void setWindowVisible(bool visibility) nogil

        void setSoundEnabled(bool sound) nogil

        void addAvailableButton(Button button) nogil

        void setButtonMaxValue(Button button, int maxValue) nogil

        void clearAvailableButtons() nogil

        void setMode(Mode mode) nogil

        void setSeed(unsigned int seed) nogil

        void newEpisode() nogil

        bool init() nogil

        ScreenFormat getScreenFormat() nogil

        int getScreenWidth() nogil

        int getScreenHeight() nogil

        int getScreenChannels() nogil

        const np.uint8_t* getGameScreen() nogil

        void setAction(const vector[int]& actions) nogil

        void advanceAction(unsigned int tics, bool updateState, bool renderOnly) nogil

        bool isEpisodeFinished() nogil

        double getTotalReward() nogil

        int getGameVariable(GameVariable var) nogil



cdef class ParDoom(object):
    cdef int n_envs
    cdef vector[DoomGame*] games

    def __cinit__(self, int n_envs):
        self.n_envs = n_envs
        self.games.resize(n_envs)
        self.create_all()

    def close_all(self, np.int32_t[:] mask=None):
        cdef int i
        cdef bool no_mask = mask is None
        if self.n_envs == 1:
            for i in range(self.n_envs):
                if no_mask or mask[i]:
                    if self.games[i] != NULL:
                        self.games[i].close()
                        del self.games[i]
                        self.games[i] = NULL
        else:
            with nogil, parallel():
                for i in prange(self.n_envs):
                    if no_mask or mask[i]:
                        if self.games[i] != NULL:
                            self.games[i].close()
                            del self.games[i]
                            self.games[i] = NULL

    def create_all(self, np.int32_t[:] mask=None):
        cdef int i
        cdef bool no_mask = mask is None
        if self.n_envs == 1:
            for i in range(self.n_envs):
                if no_mask or mask[i]:
                    if self.games[i] != NULL:
                        self.games[i].close()
                        del self.games[i]
                    self.games[i] = new DoomGame()
        else:
            with nogil, parallel():
                for i in prange(self.n_envs):
                    if no_mask or mask[i]:
                        if self.games[i] != NULL:
                            self.games[i].close()
                            del self.games[i]
                        self.games[i] = new DoomGame()

    def init_all(self, np.int32_t[:] mask=None):
        cdef int i
        cdef bool no_mask = mask is None
        # if self.n_envs == 1:
        #     for i in range(self.n_envs):
        #         if no_mask or mask[i]:
        #             self.games[i].init()
        # else:
        #     with nogil, parallel():
        for i in range(self.n_envs):
            if no_mask or mask[i]:
                self.games[i].init()

    def new_episode_all(self, np.int32_t[:] mask=None):
        cdef int i
        cdef bool no_mask = mask is None
        if self.n_envs == 1:
            for i in range(self.n_envs):
                if no_mask or mask[i]:
                    self.games[i].newEpisode()
        else:
            with nogil, parallel():
                for i in prange(self.n_envs):
                    if no_mask or mask[i]:
                        self.games[i].newEpisode()

    def set_vizdoom_path(self, int i, const string& path):
        self.games[i].setViZDoomPath(path)

    def set_doom_game_path(self, int i, const string& path):
        self.games[i].setDoomGamePath(path)

    def set_doom_scenario_path(self, int i, const string& path):
        self.games[i].setDoomScenarioPath(path)

    def set_doom_map(self, int i, const string& map):
        self.games[i].setDoomMap(map)

    def get_doom_map(self, int i):
        return self.games[i].getDoomMap()

    def set_screen_resolution(self, int i, ScreenResolution resolution):
        self.games[i].setScreenResolution(resolution)

    def set_screen_format(self, int i, ScreenFormat format):
        self.games[i].setScreenFormat(format)

    def set_render_hud(self, int i, bool hud):
        self.games[i].setRenderHud(hud)

    def set_render_crosshair(self, int i, bool crosshair):
        self.games[i].setRenderCrosshair(crosshair)

    def set_render_weapon(self, int i, bool weapon):
        self.games[i].setRenderWeapon(weapon)

    def set_render_decals(self, int i, bool decals):
        self.games[i].setRenderDecals(decals)

    def set_render_particles(self, int i, bool particles):
        self.games[i].setRenderParticles(particles)

    def set_living_reward(self, int i, double livingReward):
        self.games[i].setLivingReward(livingReward)

    def set_window_visible(self, int i, bool visible):
        self.games[i].setWindowVisible(visible)

    def set_sound_enabled(self, int i, bool sound):
        self.games[i].setSoundEnabled(sound)

    def add_available_button(self, int i, Button button):
        self.games[i].addAvailableButton(button)

    def set_button_max_value(self, int i, Button button, int max_value):
        self.games[i].setButtonMaxValue(button, max_value)

    def clear_available_buttons(self, int i):
        self.games[i].clearAvailableButtons()

    def set_mode(self, int i, Mode mode):
        self.games[i].setMode(mode)

    def set_seed(self, int i, unsigned int seed):
        self.games[i].setSeed(seed)

    def set_action(self, int i, np.ndarray[int, ndim=1, mode="c"] actions not None):
        cdef vector[int] vec_actions
        vec_actions.assign(&actions[0], &actions[-1]+1)
        self.games[i].setAction(vec_actions)

    def get_game_screen_shape(self, int i):
        cdef ScreenFormat format = self.games[i].getScreenFormat()
        cdef int channels = self.games[i].getScreenChannels()
        cdef int width = self.games[i].getScreenWidth()
        cdef int height = self.games[i].getScreenHeight()

        if format == ScreenFormat.CRCGCB or \
                        format == ScreenFormat.CRCGCBDB or \
                        format == ScreenFormat.CBCGCR or \
                        format == ScreenFormat.CBCGCRDB or \
                        format == ScreenFormat.GRAY8 or \
                        format == ScreenFormat.DEPTH_BUFFER8 or \
                        format == ScreenFormat.DOOM_256_COLORS8:
            return (channels, height, width)
        else:
            return (height, width, channels)

    def get_game_screen_all(self):
        ret = []
        cdef np.uint8_t[:,:,:] screen
        for i in range(self.n_envs):
            shape = self.get_game_screen_shape(i)
            screen = <np.uint8_t[:shape[0],:shape[1],:shape[2]]> self.games[i].getGameScreen()
            ret.append(np.asarray(screen))#screen[:shape[0], :shape[1], :shape[2]], dtype=np.uint8))
        return ret

    def advance_action_all(self, unsigned int tics, bool update_state, bool render_only):
        cdef int i
        if self.n_envs == 1:
            for i in range(self.n_envs):
                self.games[i].advanceAction(tics, update_state, render_only)
        else:
            with nogil, parallel():
                for i in prange(self.n_envs):
                    self.games[i].advanceAction(tics, update_state, render_only)

    def advance_action_all_frame_skips(self, np.int32_t[:] tics, bool update_state, bool render_only):
        cdef int i
        if self.n_envs == 1:
            for i in range(self.n_envs):
                self.games[i].advanceAction(tics[i], update_state, render_only)
        else:
            with nogil, parallel():
                for i in prange(self.n_envs):
                    self.games[i].advanceAction(tics[i], update_state, render_only)

    def is_episode_finished(self, int i):
        return self.games[i].isEpisodeFinished()

    def get_total_reward(self, int i):
        return self.games[i].getTotalReward()

    def get_game_variable(self, int i, GameVariable var):
        return self.games[i].getGameVariable(var)