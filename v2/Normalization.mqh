#ifndef GOAT_V2_NORMALIZATION_MQH
#define GOAT_V2_NORMALIZATION_MQH

// V1 serialized every positive distance input as ten broker points on every
// symbol, including two- and four-digit feeds.  Keep that migration contract
// explicit instead of silently reinterpreting existing GOAT settings.
double V2V1ConfiguredPipSize(const double point)
  {
   if(!MathIsValidNumber(point) || point<=0.0)
      return 0.0;
   return point*10.0;
  }

double V2PriceIncrement(const double tick_size,const double point)
  {
   if(MathIsValidNumber(tick_size) && tick_size>0.0)
      return tick_size;
   if(MathIsValidNumber(point) && point>0.0)
      return point;
   return 0.0;
  }

double V2NormalizeMarketPrice(const double price,
                              const double tick_size,
                              const double point)
  {
   if(!MathIsValidNumber(price) || price<=0.0)
      return 0.0;
   const double increment=V2PriceIncrement(tick_size,point);
   if(increment<=0.0)
      return 0.0;
   return NormalizeDouble(MathRound(price/increment)*increment,12);
  }

double V2PriceEpsilon(const double tick_size,const double point)
  {
   return MathMax(V2PriceIncrement(tick_size,point),1e-12)*0.5;
  }

// A broker volume step is a normalization/comparison rule, not evidence that
// a smaller real position is absent. Position presence and exact fill
// accounting therefore use only a floating-point noise floor.
double V2PhysicalVolumeEpsilon(void)
  {
   return 1e-12;
  }

bool V2HasPhysicalVolume(const double volume)
  {
   return(MathIsValidNumber(volume) && volume>V2PhysicalVolumeEpsilon());
  }

bool V2ExecutedVolumeSatisfies(const double executed,const double requested)
  {
   if(!MathIsValidNumber(executed) || !MathIsValidNumber(requested) ||
      executed<0.0 || requested<=0.0)
      return false;
   return(executed+V2PhysicalVolumeEpsilon()>=requested);
  }

#endif
