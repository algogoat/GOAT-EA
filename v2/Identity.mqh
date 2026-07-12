#ifndef GOAT_V2_IDENTITY_MQH
#define GOAT_V2_IDENTITY_MQH

#include "Domain.mqh"

class CV2Identity
  {
private:
   string m_deployment_id;
   string m_generation_id;
   string m_member_id;
   ulong  m_magic;

   bool Sha256(const string value,uchar &digest[]) const
     {
      uchar data[];
      uchar key[];
      ArrayResize(data,0);
      ArrayResize(key,0);
      int count=StringToCharArray(value,data,0,WHOLE_ARRAY,CP_UTF8);
      if(count<=0)
         return false;
      if(data[count-1]==0)
         ArrayResize(data,count-1);
      ArrayResize(digest,0);
      ResetLastError();
      int result=CryptEncode(CRYPT_HASH_SHA256,data,key,digest);
      return(result==32 && ArraySize(digest)==32);
     }

   string DigestHex(const uchar &digest[]) const
     {
      string value="";
      const int count=ArraySize(digest);
      for(int i=0;i<count;i++)
         value+=StringFormat("%02X",(int)digest[i]);
      return value;
     }

   bool StableId(const string prefix,const string material,string &identity) const
     {
      uchar digest[];
      if(!Sha256(material,digest))
        {
         identity="";
         return false;
        }
      string hex=DigestHex(digest);
      identity=prefix+StringSubstr(hex,0,32);
      return true;
     }

   bool Hash53(const string value,ulong &hash) const
     {
      hash=0;
      uchar digest[];
      if(!Sha256(value,digest))
         return false;
      for(int i=0;i<8;i++)
         hash=(hash<<8)|(ulong)digest[i];
      hash&=0x001FFFFFFFFFFFFF;
      if(hash==0)
         hash=1;
      return true;
     }

public:
                     CV2Identity(void)
     {
      m_deployment_id="";
      m_generation_id="";
      m_member_id="";
      m_magic=0;
     }

   bool Initialize(const string deployment_key,
                   const string generation_key,
                   const string member_key,
                   string &reason)
     {
      reason="";
      if(StringLen(deployment_key)<3)
        {
         reason="DEPLOYMENT_KEY_TOO_SHORT";
         return false;
        }
      if(StringLen(generation_key)<1)
        {
         reason="GENERATION_KEY_EMPTY";
         return false;
        }
      if(StringLen(member_key)<1)
        {
         reason="MEMBER_KEY_EMPTY";
         return false;
        }

      string account_fingerprint=StringFormat("%I64d|%s|%s",
                                              AccountInfoInteger(ACCOUNT_LOGIN),
                                              AccountInfoString(ACCOUNT_SERVER),
                                              AccountInfoString(ACCOUNT_CURRENCY));
      if(!StableId("dep_","GOAT2|DEPLOYMENT|"+deployment_key+"|"+account_fingerprint,m_deployment_id) ||
         !StableId("gen_","GOAT2|GENERATION|"+generation_key,m_generation_id) ||
         !StableId("mem_","GOAT2|MEMBER|"+deployment_key+"|"+member_key,m_member_id))
        {
         reason="IDENTITY_HASH_FAILED";
         return false;
        }
      if(!Hash53("GOAT2|MAGIC|"+m_deployment_id+"|"+m_member_id,m_magic))
        {
         reason="MAGIC_HASH_FAILED";
         return false;
        }
      return true;
     }

   string DeploymentId(void) const { return m_deployment_id; }
   string GenerationId(void) const { return m_generation_id; }
   string MemberId(void) const { return m_member_id; }
   ulong  Magic(void) const { return m_magic; }

   string MagicTransport(void) const
     {
      return StringFormat("%I64u",m_magic);
     }

   bool SequenceId(const ENUM_V2_DIRECTION direction,const long reserved_ordinal,string &identity) const
     {
      if(reserved_ordinal<=0)
        {
         identity="";
         return false;
        }
      return StableId("seq_",StringFormat("GOAT2|SEQUENCE|%s|%s|%d|%I64d",
                                           m_deployment_id,m_member_id,(int)direction,reserved_ordinal),identity);
     }

   bool OrderIntentId(const string sequence_id,
                      const ENUM_V2_ACTION_KIND action,
                      const long reserved_ordinal,
                      string &identity) const
     {
      if(sequence_id=="" || reserved_ordinal<=0)
        {
         identity="";
         return false;
        }
      return StableId("int_",StringFormat("GOAT2|INTENT|%s|%d|%I64d",
                                           sequence_id,(int)action,reserved_ordinal),identity);
     }

   bool SystemExitIntentId(const string sequence_id,
                           const ulong deal_ticket,
                           string &identity) const
     {
      if(sequence_id=="" || deal_ticket==0)
        {
         identity="";
         return false;
        }
      return StableId("int_",StringFormat("GOAT2|SYSTEM_EXIT|%s|%I64u",
                                           sequence_id,deal_ticket),identity);
     }

   bool EventId(const string canonical_payload,string &identity) const
     {
      return StableId("evt_","GOAT2|EVENT|"+canonical_payload,identity);
     }

   bool ReceiptId(const string canonical_payload,string &identity) const
     {
      return StableId("rcp_","GOAT2|RECEIPT|"+canonical_payload,identity);
     }

   bool MagicCollides(const ulong other_magic,const string other_member_id) const
     {
      return(other_magic==m_magic && other_member_id!="" && other_member_id!=m_member_id);
     }
  };

#endif
