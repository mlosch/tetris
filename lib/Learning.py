import numpy as np
from pyglet.window import key
import random
import util
import math

import theano
import theano.tensor as T
import lasagne


class WorldFeedback(object):
    def getreward(self):
        raise NotImplementedError

class RLLearner(object):
    _moves = [key.MOTION_DOWN, key.MOTION_LEFT, key.MOTION_RIGHT, key.MOTION_UP]  # Do nothing, Move left, Move right

    def __init__(self, board, worldfeedback, learningrate, discountfactor):
        self.board = board
        self.feedback = worldfeedback
        self.lr = learningrate
        self.gamma = discountfactor

    def reset(self):
        pass

    def step(self):
        return random.choice(self._moves)


class QLearner(RLLearner):

    def __init__(self, board, worldfeedback, learningrate=0.01, discountfactor=0.6, epsilon=0.1):
        super(QLearner, self).__init__(board, worldfeedback, learningrate, discountfactor)
        self.epsilon = epsilon

        self.lastState = None
        self.lastAction = 0

        self.reset()

        self.policy = {}
        self._createpolicyentry(self.lastState)

    def _createpolicyentry(self, state):
        self.policy[state] = np.random.rand(len(self._moves))

    def reset(self):
        self.lastState = self.board.encode()
        self.lastAction = 0

    def newpiece(self):
        # self.lastAction = 0
        pass

    def softmax(self, state):
        p = [math.exp(a) for a in self.policy[state]]
        s = sum(p)
        return [v/s for v in p]

    def _nextaction(self, state):
        # return util.choosewithprob(self.softmax(state))
        if random.random() < self.epsilon:
            return random.randint(0, len(self.policy[state])-1)
        else:
            return np.argmax(self.policy[state])

    def _updatevalue(self, state, action, reward):
        # Q-Learning always updates with the argmax action:
        action = np.argmax(self.policy[state])
        self.policy[self.lastState][self.lastAction] += self.lr * (reward + self.gamma * self.policy[state][action] - self.policy[self.lastState][self.lastAction])

    def step(self):
        # encode board into state
        state = self.board.encode()

        # choose action from policy table
        if state not in self.policy:
            self._createpolicyentry(state)

        action = self._nextaction(state)

        reward = self.feedback.getreward()

        # print(len(self.policy), state)
        # print(len(self.policy), self.policy[state], reward)

        self._updatevalue(state, action, reward)

        self.lastState = state
        self.lastAction = action

        return self._moves[action]


class SarsaLearner(QLearner):
    def _updatevalue(self, state, action, reward):
        # SARSA-Learning always updates with the chosen action:
        self.policy[self.lastState][self.lastAction] += self.lr * (reward + self.gamma * self.policy[state][action] - self.policy[self.lastState][self.lastAction])


class SarsaLambdaLearner(QLearner):
    """
    Implements SARSA with eligibility traces.
    """
    def __init__(self, board, worldfeedback, learningrate=0.01, discountfactor=0.6, epsilon=0.1, lam=0.9):
        self.lam = lam
        #self.e = {}
        self.track = []
        super(SarsaLambdaLearner, self).__init__(board, worldfeedback, learningrate, discountfactor, epsilon)

    def newpiece(self):
        super(SarsaLambdaLearner, self).newpiece()
        # self.track = []

    def reset(self):
        super(SarsaLambdaLearner, self).reset()
        self.track = []

    def _updatevalue(self, state, action, reward):
        delta = reward + self.gamma * self.policy[state][action] - self.policy[self.lastState][self.lastAction]

        hit = False
        for i in range(len(self.track)):
            if self.track[i][1] == self.lastAction and self.track[i][0] == self.lastState:
                self.track[i][2] += 1
                hit = True
                break

        if not hit:
            self.track.append([self.lastState, self.lastAction, 1])

        clearids = set()

        for i in range(len(self.track)):
            s, a, e = self.track[i]
            self.policy[s][a] += self.lr * delta * e
            self.track[i][2] *= self.gamma * self.lam

            if self.track[i][2] < 1e-6:
                clearids.add(i)

        if len(clearids) > 0:
            self.track = [t for i, t in enumerate(self.track) if i not in clearids]

        # for s in self.policy.keys():
        #     for ai in range(len(self._moves)):
        #         self.policy[s][ai] += self.lr * delta * self.e[s][ai]
        #         self.e[s][ai] *= self.gamma * self.lam


class DeepQLearner(RLLearner):
    def __init__(self, board, worldfeedback, learningrate=0.01, discountfactor=0.6, rho=0.99, rms_epsilon=1e-6):
        super(DeepQLearner, self).__init__(board, worldfeedback, learningrate, discountfactor)

        input_scale = 2.0

        last_state = T.tensor4('last_state')
        last_action = T.icol('last_action')
        state = T.tensor4('state')
        reward = T.col('reward')

        self.state_shared = theano.shared(np.zeros((1,1,board.height, board.width), dtype=theano.config.floatX))
        self.last_state_shared = theano.shared(np.zeros((1,1,board.height, board.width), dtype=theano.config.floatX))
        self.last_action_shared = theano.shared(np.zeros((1,1), dtype='int32'), broadcastable=(False, True))
        self.reward_shared = theano.shared(np.zeros((1,1), dtype=theano.config.floatX), broadcastable=(False, True))

        model = lasagne.layers.InputLayer(shape=(1, 1, board.height, board.width))
        model = lasagne.layers.Conv2DLayer(model, 24, 3, pad=1)
        model = lasagne.layers.Conv2DLayer(model, 48, 3, pad=1)
        model = lasagne.layers.Conv2DLayer(model, 12, 3, pad=1)
        model = lasagne.layers.DenseLayer(model, 256)
        #model = lasagne.layers.DropoutLayer(model, 0.5)
        model = lasagne.layers.DenseLayer(model, 256)
        #model = lasagne.layers.DropoutLayer(model, 0.5)
        model = lasagne.layers.DenseLayer(model, len(self._moves), nonlinearity=lasagne.nonlinearities.identity)

        lastQvals = lasagne.layers.get_output(model, last_state / input_scale)
        Qvals = lasagne.layers.get_output(model, state / input_scale)
        Qvals = theano.gradient.disconnected_grad(Qvals)

        delta = reward + self.gamma * T.max(Qvals, axis=1, keepdims=True) - \
                lastQvals[T.arange(1), last_action.reshape((-1,))].reshape((-1,1))

        loss = T.mean(0.5 * delta ** 2)

        params = lasagne.layers.get_all_params(model)
        givens = {
            state: self.state_shared,
            last_state: self.last_state_shared,
            last_action: self.last_action_shared,
            reward: self.reward_shared,
        }
        updates = lasagne.updates.rmsprop(loss, params, learning_rate=self.lr, rho=rho, epsilon=rms_epsilon)

        self.model = model
        self.train_fn = theano.function([], [loss, Qvals], updates=updates, givens=givens)
        self.Qvals = theano.function([], Qvals, givens={state: self.state_shared})

        self.last_state = self.board.encode_image()
        self.last_state = self.last_state[np.newaxis, np.newaxis, ...]
        self.last_action = np.zeros((1, 1), dtype='int32')

    def reset(self):
        pass

    def step(self):
        state = self.board.encode_image()
        state = state[np.newaxis, np.newaxis, ...]

        self.last_state_shared.set_value(self.last_state)
        self.state_shared.set_value(state)

        reward = np.zeros((1,1), dtype=theano.config.floatX)
        reward[0] = self.feedback.getreward()

        self.last_action_shared.set_value(self.last_action)
        self.reward_shared.set_value(reward)

        loss, qvals = self.train_fn()

        print(loss)

        np.argmax(qvals, self.last_action)
        self.last_state = state

        return self.last_action

# def _updatevalue(self, state, action, reward):
#     # Q-Learning always updates with the argmax action:
#     action = np.argmax(self.policy[state])
#     self.policy[self.lastState][self.lastAction] += self.lr * (reward + self.gamma * self.policy[state][action] - self.policy[self.lastState][self.lastAction])
#
# def step(self):
#     # encode board into state
#     state = self.board.encode()
#
#     # choose action from policy table
#     if state not in self.policy:
#         self._createpolicyentry(state)
#
#     action = self._nextaction(state)
#
#     reward = self.feedback.getreward()
#
#     # print(len(self.policy), state)
#     # print(len(self.policy), self.policy[state], reward)
#
#     self._updatevalue(state, action, reward)
#
#     self.lastState = state
#     self.lastAction = action
#
#     return self._moves[action]