#External Imports
import numpy as np 
import pandas as pd 
from datetime import date, timedelta
from typing import Union, List, Optional
from pydantic import BaseModel, Field
from scipy import stats

#Local Imports
from .dca import DCA, ProbVar
from .timeconverter import list_freq, converter_factor, time_converter_matrix, check_value_or_prob, FreqEnum


def bsw_to_wor(bsw):
    assert isinstance(bsw,(int,float,np.ndarray,pd.Series))
    bsw = np.atleast_1d(bsw)
    assert np.all((bsw>=0)&(bsw<=1))
    wor = bsw/(1-bsw)
    return wor 

def wor_to_bsw(wor):
    assert isinstance(wor,(int,float,np.ndarray,pd.Series))
    wor = np.atleast_1d(wor)
    assert np.all(wor>=0)
    bsw = wor/(wor+1)
    return bsw   

def wor_forecast(time_array:np.ndarray,fluid_rate:Union[float,np.ndarray], slope:float, 
	wor_i:float, rate_limit:float = None,cum_limit:float=None, wor_limit:float=None):


    time_array = np.atleast_1d(time_array)
    fluid_rate = np.atleast_1d(fluid_rate)

    #delta_time = np.diff(time_array,append=0)
    delta_time = np.gradient(time_array)

    wor_i1 = wor_i + 1

    # Create arrays
    wor = np.zeros(time_array.shape[0])
    wor[0] = wor_i


    wor_1 = np.zeros(time_array.shape[0])
    wor_1[0] = wor_i + 1

    bsw = np.zeros(time_array.shape[0])
    bsw[0] = wor_to_bsw(wor[0])

    oil_rate = np.zeros(time_array.shape[0])
    oil_rate[0] = fluid_rate[0]*(1-bsw[0])
    water_rate = np.zeros(time_array.shape[0])
    water_rate[0]=fluid_rate[0]*bsw[0]

    oil_cum = np.zeros(time_array.shape[0])
    oil_cum[0] = oil_rate[0]*delta_time[0]

    water_cum = np.zeros(time_array.shape[0])
    water_cum[0] = water_rate[0]*delta_time[0]

    fluid_cum = np.zeros(time_array.shape[0])
    fluid_cum[0] = fluid_rate[0]*delta_time[0]

    for i in range(1,delta_time.shape[0]-1):
        wor[i] = np.exp(slope*oil_cum[i-1])*wor_i
        wor_1[i] = wor[i] + 1
        bsw[i] = wor_to_bsw(wor[i])
        oil_rate[i] = fluid_rate[i]*(1-bsw[i])
        water_rate[i] = fluid_rate[i]*bsw[i]
        oil_cum[i] = oil_cum[i-1] + oil_rate[i]*delta_time[i]
        water_cum[i] = water_cum[i-1] + water_rate[i]*delta_time[i]
        fluid_cum[i] = water_cum[i] + oil_cum[i]
        if rate_limit:
            if oil_rate[i] <= rate_limit:
                break

        if cum_limit:
            if oil_cum[i] >= cum_limit:
                break     

        if wor_limit:
            if wor[i] >= wor_limit:
                break          

    _forecast = pd.DataFrame(
    	{
            'oil_rate':oil_rate,
            'water_rate':water_rate,
            'oil_cum':oil_cum,
            'water_cum':water_cum,
            'bsw':bsw,
            'wor':wor,
            'wor_1':wor_1,
            'delta_time':delta_time,
            'fluid_rate':fluid_rate,
            'fluid_cum' : fluid_cum
            },
            index = time_array
    )
    
    _forecast.index.name = 'date'

    return _forecast[:i+1]



class Wor(BaseModel,DCA):

    bsw: Union[ProbVar,List[float],float] = Field(...)
    slope: Union[ProbVar,List[float],float] = Field(...)
    fluid_rate : Union[float,List[float],List[List[float]]] = Field(...)
    ti: Union[int,date] = Field(...)
    seed : Optional[int] = Field(None)
    gor: Optional[Union[float,List[float]]] = Field(None)
    glr: Optional[Union[float,List[float]]] = Field(None)


    class Config:
        arbitrary_types_allowed = True

    def get_bsw(self,size=None, ppf=None):
        """get_bsw get the number of bsw

        Args:
            size ([type], optional): number of iterations. Defaults to None.
            ppf ([type], optional): percentil. Defaults to None.

        Returns:
            np.array: Array if bsw
        """
        if isinstance(self.bsw,ProbVar):
            return self.bsw.get_sample(size=size, ppf=ppf)
        else:
            return np.atleast_1d(self.bsw)

    def get_slope(self,size=None, ppf=None):
        """get_slope get the number of slope

        Args:
            size ([type], optional): number of iterations. Defaults to None.
            ppf ([type], optional): percentil. Defaults to None.

        Returns:
            np.array: Array if slope
        """
        if isinstance(self.slope,ProbVar):
            return self.slope.get_sample(size=size, ppf=ppf)
        else:
            return np.atleast_1d(self.slope)

    def format(self):
        if isinstance(self.ti,date):
            return 'date'
        else:
            return 'number'

    def forecast(self,time_list:Union[pd.Series,np.ndarray]=None,start:Union[date,float]=None, 
    	end:Union[date,float]=None, fluid_rate:Union[float,list]=None,rate_limit:float=None,cum_limit:float=None, wor_limit:float=None,
    	freq_input:str='D', freq_output:str='M', iter:int=1,ppf=None,**kwargs)->pd.DataFrame:

        if self.format() == 'date':
            freq_input = 'D'
            #Check if the time range was given. If True, use this to estimate the time array for
            # the Forecast
            if time_list is not None:
                assert isinstance(time_list, (pd.Series, np.ndarray)), f'Must be np.array or pd.Series with dtype datetime64. {type(time_list)} was given'
                assert np.issubdtype(time_list.dtype, np.datetime64), f'dtype must be datetime64. {time_list.dtype} was given'
                time_list = pd.Series(time_list).dt.to_period(freq_input)
            else:
                assert all(isinstance(i,date) for i in [start,end])
                time_list = pd.period_range(start=start, end=end, freq=freq_input)

            time_range = pd.Series(time_list)
            time_array = time_range.apply(lambda x: x.to_timestamp().toordinal()) - self.ti.toordinal()
            time_array = time_array.values
        else:
            if time_list is not None:
                time_list = np.atleast_1d(time_list)
                assert isinstance(time_list, (pd.Series, np.ndarray)), f'Must be np.array or pd.Series with dtype datetime64. {type(time_list)} was given'
                assert np.issubdtype(time_list.dtype, np.integer), f'dtype must be integer. {time_list.dtype} was given'
            else:
                assert all(isinstance(i,(int,float)) for i in [start,end])     
                fq = converter_factor(freq_input,freq_output)
                assert fq>=1, 'The output frecuency must be greater than input'
                time_list = np.arange(start, end, 1)

            time_array = time_list
            time_range = time_list



       	#Broadcast variables to set the total iterations

        #Get bsw and slope
        bsw = self.get_bsw(size=iter, ppf=ppf)
        slope = self.get_slope(size=iter, ppf=ppf)

        #Get the fluid Rate. 
        # If the result is a 2D numpy array the size must match the Time array 
        # with the form [iterations, time_array].
        #
        #If the result is 1D, the length of the vector is the number of iterations will be performed
        #This vector is broadcasted to a 2D array that match the time_array shape
        fluid_rate = np.atleast_1d(self.fluid_rate)

        #Broadcast three variables
        br = np.broadcast(bsw,slope,np.zeros(fluid_rate.shape[0]))
        
        #Convert varibles into broadcast shape
        _bsw = bsw * np.ones(br.shape)
        _slope = slope * np.ones(br.shape)

        # make the fluid array to be consistent with the time array
        if fluid_rate.ndim == 1:
            _fluid = fluid_rate.reshape(-1,1) * np.ones((br.shape[0],time_array.shape[0]))
        else:
            br2 = np.broadcast(np.zeros(fluid_rate.shape[1]),time_array)
            _fluid = fluid_rate * np.ones(br2.shape)


        # Make the loop for the forecast
        list_forecast = []

        for i in range(br.shape[0]):
            _wor = bsw_to_wor(_bsw[i])

            #The fluid rate is multiplied by a factor to estimate the cumulative production.            
            _f = wor_forecast(time_array,_fluid[i], _slope[i], _wor, rate_limit=rate_limit,
                cum_limit=cum_limit, wor_limit=wor_limit)
            
            _f['iteration'] = i
            #_f.index = time_range[1:_f.shape[0]+1]
            _f.index = time_range[0:_f.shape[0]]

            _f['oil_volume'] = np.gradient(_f['oil_cum'].values)
            _f['water_volume'] = np.gradient(_f['water_cum'].values)
 

            #Gas Rate
            if any([i is not None for i in [self.gor,self.glr]]):

                if self.gor:
                    _f['gas_cum'] = _f['oil_cum'].multiply(self.gor) 
                    _f['gas_volume'] = np.diff(_f['gas_cum'], prepend=0) #/ _f['delta_time']
                    _f['gas_rate'] = _f['gas_volume'] / _f['delta_time']
                elif self.glr:
                    _f['gas_cum'] = _f['oil_cum'].add(_f['water_cum']).multiply(self.glr) 
                    _f['gas_volume'] = np.diff(_f['gas_cum'], prepend=0) / _f['delta_time']
                    _f['gas_rate'] = _f['gas_volume'] / _f['delta_time']
            else:
                _f['gas_cum'] = 0
                _f['gas_volume'] = 0
                _f['gas_rate'] = 0

            
            list_forecast.append(_f)


        _forecast = pd.concat(list_forecast, axis=0)
        _forecast.index.name = 'date'
        
        if self.format() == 'date' and freq_output!='D':
            _forecast = _forecast.to_timestamp().to_period(freq=freq_output)
            _forecast.reset_index(inplace=True)
            _forecast = _forecast.groupby(
                ['date','iteration']
            ).agg({
                'oil_rate':'mean',
                'water_rate':'mean',
                'oil_cum':'max',
                'gas_rate':'mean',
                'water_cum':'max',
                'bsw':'mean',
                'wor':'mean',
                'wor_1':'mean',
                'delta_time':'mean',
                'fluid_rate':'mean',
                'fluid_cum' : 'max',
                'gas_cum' : 'max',
                'oil_volume':'sum',
                'water_volume':'sum',
                'gas_volume':'sum'
            }).reset_index().set_index('date')

        return _forecast










