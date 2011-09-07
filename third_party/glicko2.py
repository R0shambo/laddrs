"""
Copyright (c) 2009 Ryan Kirkman

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
"""

import logging
import math

MAX_RD = 350.0 / 173.7178

class Player:
    # Class attribute
    # The system constant, which constrains
    # the change in volatility over time.
    _tau = 0.5

    def getRating(self):
        return self.__rating * 173.7178 + 1500.0

    def setRating(self, rating):
        self.__rating = (rating - 1500.0) / 173.7178

    rating = property(getRating, setRating)

    def getRd(self):
        #thisrd = self.__rd * 173.7178
        #logging.info("%s getRd %f * 173.7178 = %f", self.name, self.__rd, thisrd)
        return self.__rd * 173.7178

    def setRd(self, rd):
        self.__rd = min(rd / 173.7178, MAX_RD)

    rd = property(getRd, setRd)

    def __init__(self, rating = 1500.0, rd = 350.0, vol = 0.06, name = 'player'):
        # For testing purposes, preload the values
        # assigned to an unrated player.
        self.setRating(rating)
        self.setRd(rd)
        self.vol = vol
        self.name = name

    def _preRatingRD(self):
        """ Calculates and updates the player's rating deviation for the
        beginning of a rating period.

        preRatingRD() -> None

        """
        self.__rd = min(math.sqrt(math.pow(self.__rd, 2.0) + math.pow(self.vol, 2.0)),
            MAX_RD)


    def update_player(self, rating_list, RD_list, outcome_list):
        """ Calculates the new rating and rating deviation of the player.

        update_player(list[int], list[int], list[bool]) -> None

        """
        #logging.info("%s's results %s %s %s", self.name, str(rating_list), str(RD_list), str(outcome_list))
        #logging.info("%s was %f/%f/%f", self.name, self.rating, self.rd, self.vol)
        #logging.info("%s's pre-rating %f/%f", self.name, self.__rating, self.__rd)

        # Convert the rating and rating deviation values for internal use.
        rating_list = [(x - 1500.0) / 173.7178 for x in rating_list]
        RD_list = [x / 173.7178 for x in RD_list]

        v = self._v(rating_list, RD_list)
        self.vol = self._newVol(rating_list, RD_list, outcome_list, v)
        self._preRatingRD()

        self.__rd = min(1.0 / math.sqrt((1.0 / math.pow(self.__rd, 2.0)) + (1.0 / v)),
            MAX_RD)

        tempSum = 0.0
        for i in range(len(rating_list)):
            tempSum += self._g(RD_list[i]) * \
                       (outcome_list[i] - self._E(rating_list[i], RD_list[i]))
        self.__rating += math.pow(self.__rd, 2.0) * tempSum

        #logging.info("%s's post-rating %f/%f", self.name, self.__rating, self.__rd)
        #logging.info("%s updated to %f/%f/%f", self.name, self.rating, self.rd, self.vol)


    def _newVol(self, rating_list, RD_list, outcome_list, v):
        """ Calculating the new volatility as per the Glicko2 system.

        _newVol(list, list, list) -> float

        """
        #i = 0
        delta = self._delta(rating_list, RD_list, outcome_list, v)
        a = math.log(math.pow(self.vol, 2.0))
        tau = self._tau
        x0 = a
        x1 = 0.0

        while x0 != x1:
            # New iteration, so x(i) becomes x(i-1)
            x0 = x1
            d = math.pow(self.__rating, 2.0) + v + math.exp(x0)
            h1 = (-(x0 - a) / math.pow(tau, 2.0) - 0.5 * math.exp(x0)
                / d + 0.5 * math.exp(x0) * math.pow(delta / d, 2.0))
            h2 = (-1.0 / math.pow(tau, 2.0) - 0.5 * math.exp(x0) *
                (math.pow(self.__rating, 2.0) + v)
                / math.pow(d, 2.0) + 0.5 * math.pow(delta, 2.0) * math.exp(x0)
                * (math.pow(self.__rating, 2.0) + v - math.exp(x0)) / math.pow(d, 3.0))
            x1 = x0 - (h1 / h2)

        return math.exp(x1 / 2.0)

    def _delta(self, rating_list, RD_list, outcome_list, v):
        """ The delta function of the Glicko2 system.

        _delta(list, list, list) -> float

        """
        tempSum = 0
        for i in range(len(rating_list)):
            tempSum += self._g(RD_list[i]) * (outcome_list[i] - self._E(rating_list[i], RD_list[i]))
        return v * tempSum

    def _v(self, rating_list, RD_list):
        """ The v function of the Glicko2 system.

        _v(list[int], list[int]) -> float

        """
        tempSum = 0.0
        for i in range(len(rating_list)):
            tempE = self._E(rating_list[i], RD_list[i])
            tempSum += math.pow(self._g(RD_list[i]), 2.0) * tempE * (1.0 - tempE)
        return 1.0 / tempSum

    def _E(self, p2rating, p2RD):
        """ The Glicko E function.

        _E(int) -> float

        """
        return (1.0 / (1.0 + math.exp(-1.0 * self._g(p2RD) *
                                 (self.__rating - p2rating))))

    def _g(self, RD):
        """ The Glicko2 g(RD) function.

        _g() -> float

        """
        return 1.0 / math.sqrt(1.0 + 3.0 * math.pow(RD, 2.0) / math.pow(math.pi, 2.0))

    def did_not_compete(self):
        """ Applies Step 6 of the algorithm. Use this for
        players who did not compete in the rating period.

        did_not_compete() -> None

        """
        self._preRatingRD()
        #logging.info("%s updated to %f/%f/%f", self.name, self.rating, self.rd, self.vol)

