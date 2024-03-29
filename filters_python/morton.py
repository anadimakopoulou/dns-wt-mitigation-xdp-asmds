import os,sys,time
import mmh3
from bitstring import BitArray, BitStream
import math,random

HASH_SIZE = 32

def fingerprint(item, fp_size=8):
        # take first fp_size bits as fingerprint to minimize false positives
        fp = mmh3.hash(item, signed=False)  # default hash returns 32-bit
        fp = fp >> (HASH_SIZE-fp_size) # no need for mask for msb's
        if (fp == 0):
            fp = 1 # empty fingerprints are reserved to check if FSA has space
        return fill_bits(fp,fp_size) # pad with leading zeros if necessary        

def fill_bits(item,no_bits):
    """Takes as input: 
    item := the number that in binary format may have leading zeros
    no_bits := how many bits we want in binary format.
    Returns: a string representing the item with the appropriate leading zeros.
    """
    # we add +2 to no_bits to accommodate for characters '0b'
    return format(item,'#0'+str(no_bits+2)+'b')
class Block:
    def __init__(self,no,block_size=512,fingerprint_size=8,overflow_bits=16,no_buckets=64,no_slots=3,no_fingerprints=46):
        self.ota = BitArray(overflow_bits) # initialize Overflow Tracking Array - OTA
        self.fca_bits = math.ceil(math.log2(no_slots))
        self.fca = BitArray(no_buckets*self.fca_bits) # initialize Fullness Counter Array - FCA
        # initialize Fingerprint Storage Array - FSA
        self.fsa = BitArray(no_fingerprints*fingerprint_size)
        self.fp_size = fingerprint_size
        self.no_slots = no_slots
        self.no_buckets = no_buckets
        # no is used to get glbi from blk and lbi
        self.no = no
        self.no_fingerprints = no_fingerprints

    def serialize(self):
        s = BitArray()
        s.append(self.fsa)
        s.append(self.fca)
        s.append(self.ota)
        return s.bin

    def index_OTA(self,lbi):
        # there are 3 different methods to map fp to ota bit in the notes, we choose the simplest one
        return lbi % (self.ota.len)

    def set_OTA(self,lbi,verbose=False):
        index = self.index_OTA(lbi)
        if verbose:
            print(f"setting OTA bit at index:{index}, bit before set:{self.ota[index]}")
        self.ota.set(True,index)
        if verbose:
            print(f"OTA bit after set: {self.ota[index]}")
            print("~~~~~~~~~~")
        return

    def get_OTA(self,lbi):
        index = self.index_OTA(lbi)
        return self.ota[index]
    
    def has_capacity(self):
        """Checks if the block has spare capacity in its FSA."""
        # fingerprint 0 is for empty slots
        # if block has space, last fingerprint is 0
        return (self.fsa[-self.fp_size::].uint == 0)

    def bucket_capacity(self,lbi):
        """Returns the lbi bucket capacity in current block."""
        bits = self.fca_bits
        return self.fca[lbi*bits:(lbi+1)*bits].uint


    def table_simple_store(self,bucket,fp,verbose=False): ## insert will succeed because we checked it beforehand
        offset = 0
        bits = self.fca_bits
        bucket_cap = self.bucket_capacity(bucket)
        if (bucket_cap==self.no_slots or (not self.has_capacity())):
            raise Exception('error in table_store')
        # calculate the bucket offset
        for i in range(bucket):
            cap = self.bucket_capacity(i)
            offset += cap
        if verbose:
            print("inside table_simple_store")
            print(f"bucket_cap : {bucket_cap}, offset: {offset}")
        # shift by one slot (equal to self.fp_size) the elements in the fsa
        self.fsa[(offset + bucket_cap)*self.fp_size::] >>= self.fp_size
        # store the fingerprint
        self.fsa.overwrite(BitArray(fp),(offset + bucket_cap)*self.fp_size)
        # increment the fca counter
        self.fca.overwrite(BitArray(fill_bits(bucket_cap+1,bits)),bucket*bits)
        return

    def read_and_cmp(self,lbi,fp,verbose=False):
        """Reads a block at the bucket lbi and returns true if fp is in the block."""
        offset = 0
        match = False
        bucket_cap = self.bucket_capacity(lbi)
        if verbose:
            print(f"inside read_and_cmp, bucket_cap : {bucket_cap}.")
        for i in range(lbi):
            # fca is a bitarray
            # we need to count 2 bits for each bucket
            # hence this weird for loop
            cap = self.bucket_capacity(i)
            offset += cap
        if verbose:
            print(f"searching, offset = {offset}")
        for i in range(bucket_cap):
            index = offset+i
            # some pointer arithmetic to get the item from bitarray
            item = self.fsa[index*self.fp_size:(index+1)*self.fp_size]
            # for now fp is in binary string form, and item is a BitArray
            # we can directly compare them
            if verbose:
                print(f"candidate fp,index = {item.hex}, {index*self.fp_size}")
            if (item==fp):
                match = True
                if verbose:
                    print(f"item found on index:{index*self.fp_size}")
                break
            if verbose:
                print(f"result of read_and_cmp is {match}.")
                print("----------")
        return match
        


    def printFCA(self,reverse=False): # use reverse option when printing in bigendian format
        if (reverse):
            temp = BitArray(self.fca)
            temp.reverse()
            print(temp.bin)
        else:
            print(self.fca.bin)
        return
    def printFSA(self,reverse=False):
        if (reverse):
            temp = BitArray(self.fsa)
            temp.reverse()
            print(temp.bin)
        else:
            print(self.fsa.bin)
        return
    def printOTA(self,reverse=False):
        if (reverse):
            temp = BitArray(self.ota)
            temp.reverse()
            print(temp.bin)
        else:
            print(self.ota.bin)
        return
    def print_whole_block(self,reverse=False):
        s = self.serialize()
        if (reverse):
            temp = BitArray(s)
            temp.reverse()
            print(temp.bin)
        else:
            print(s.bin)
        return
        
class MortonFilter:
    # Block size is dictated by the physical block size of the
    # storage medium for which the MF is optimized. 
    # eg 512-bit block for 512-bit cache line
    # TODO: figure out how to partition the block according to block size
    # i.e. how many buckets and of what size
    # TODO: support more filter configurations than the default: 3-slot buckets with 8 bit fingerprints
    # TODO: add checks for valid sizes in block creation
    def __init__(self,no_blocks,
    block_size=512,
    fingerprint_size=8, 
    no_buckets=64,
    ota_bits=16,
    no_slots=3,
    no_fingerprints=46):
        self.no_blocks = no_blocks
        self.block_size = block_size
        self.fingerprint_size = fingerprint_size
        self.no_buckets = no_buckets
        self.Blocks = [] # filter is a list of Blocks
        #initialize the blocks
        for i in range(no_blocks):
            blk = Block(i,block_size=block_size,
            no_buckets=no_buckets,
            overflow_bits=ota_bits,
            fingerprint_size=fingerprint_size,
            no_slots=no_slots,
            no_fingerprints=no_fingerprints) # go with default numbers for now
            self.Blocks.append(blk)
   
   
    # functions from the paper,Even-odd partial key cuckoo hashing segment

    def map(self,x,n):
        """ Maps a value x between 0 and n-1 inclusive. """
        # this is naive implementation
        # there is a faster one (Lemire mod)
        return  x % n
    def offset(self,fx):
        # off_range should be a power of two so that modulo can be done with a bitwise and
        # off_range = 32
        # fx is the output of fingerprint() function, so we have to convert it to int
        integer_fp = 0
        if (isinstance(fx, str)):
            integer_fp = int(fx,2)
        elif (isinstance(fx,BitArray)):
            integer_fp = fx.uint
        else:
            integer_fp = fx # should never reach this branch
        # this is the table_based alternate bucket method, 
        # C++ implementation uses function_based which is a bit different
        offsets = [83, 149, 211, 277, 337, 397, 457, 521, 
          587, 653, 719, 787, 853, 919, 983, 1051, 1117, 1181, 1249, 1319, 1399, 
          1459, 
          1511, 1571, 1637, 1699, 1759, 1823, 1889, 1951, 2017, 1579]
        offset = offsets[integer_fp % len(offsets)]
        return offset
        # return (self.no_buckets + integer_fp % off_range) | 1
    
    def h1(self,item):
        """ Returns the number of (primary) bucket that the item hashes to. """
        return self.map(mmh3.hash(item,signed=False),self.no_buckets * self.no_blocks)
    def h2(self,item):
        """ Returns the number of (secondary) bucket that the item hashes to. """
        fp = fingerprint(item,self.fingerprint_size)
        first_hash = self.h1(item)
        # use the H' method, because H_2 from the paper doesn't play well
        offset = 0
        n = self.no_blocks * self.no_buckets
        if first_hash & 1:
            offset = self.offset(fp)
        else:
            offset = -self.offset(fp)
        second_hash = first_hash + offset
        if second_hash >= n:
            return second_hash - n
        elif second_hash < 0:
            return second_hash + n
        else:
            return second_hash
    
    def h_prime(self,bucket_index,fp):
        """ Calculates the alternate bucket for fp. Eg give bucket_index=h1 and return h2 and vice versa. """
        n = self.no_blocks * self.no_buckets
        offset = 0
        if bucket_index & 1 :
            offset = self.offset(fp)
        else:
            offset = -self.offset(fp)
        temp = bucket_index + offset
        # temp = bucket_index + ((-1)**(bucket_index & 1))*self.offset(fp)
        # return self.map(temp,n)
        if temp > n:
            return temp - n
        elif temp < 0:
            return temp + n
        else:
            return temp
    
    def insert(self,item,verbose=False):
        fp = fingerprint(item,self.fingerprint_size)
        if (self.check(item)):
            if verbose:
                print(f"item: {item} already in filter")
            return # if item seems already in the filter,don't add it again
            # that would cause duplicates that are in the same bucket and have the same fingerprint
            # and complicate eviction process
        # global bucket index
        glbi1 = self.h1(item)
        block1 = self.Blocks[glbi1//self.no_buckets]
        # local (in the block) bucket index -> 0 <= lbi <= no_buckets
        lbi1 = glbi1 % self.no_buckets
        if verbose:
            print(f"inserting item: {repr(item)} with fp: {hex(int(fp,2))}, at block:{glbi1//self.no_buckets},lbi:{glbi1%self.no_buckets} ")
        # bucket overflow: bucket lbi1 is full
        if (block1.bucket_capacity(lbi1) == block1.no_slots or \
            # block overflow: fsa is(?) full --> check if the last element is 0
            (not block1.has_capacity())):
                if verbose:
                    print(f"Block 1 overflow or bucket capacity for item: {item}")
                ## this is where we check h2(item)
                block1.set_OTA(lbi1,verbose)
                glbi2 = self.h2(item)
                block2 = self.Blocks[glbi2//self.no_buckets]
                lbi2 = glbi2 % self.no_buckets

                if (block2.bucket_capacity(lbi2) == block2.no_slots or \
                    (not block2.has_capacity())): # conflict resolution -- cuckoo hashing
                        if verbose:
                            print(f"Block 2 overflow or bucket capacity for item: {item}, proceed to conflict res")
                            print("++++++++++++")
                        self.res_conflict(block1,lbi1,fp,verbose)
                else: # insert will be a success in this branch
                    if verbose:
                        print("storing item at h2")
                        print("++++++++++++") 
                    block2.table_simple_store(lbi2, fp)
        else: # we put item at 'h1'
            if verbose:
                print("storing item at h1")
                print("++++++++++++")
            block1.table_simple_store(lbi1,fp,verbose)
        return
        
        
    def check_candidate_bucket(self,glbi,fp,verbose=False):
        """Returns true if candidate bucket is available."""
        alternate_bucket = self.h_prime(glbi,fp)
        if (alternate_bucket == self.no_buckets*self.no_blocks):
            # indexing starts at 0
            # raises ListIndexOutOfRange otherwise
            alternate_bucket = 0
        alt_blk = self.Blocks[alternate_bucket//self.no_buckets]
        alt_lbi = alternate_bucket % self.no_buckets
        alt_cap = alt_blk.bucket_capacity(alt_lbi)
        bucket_of = (alt_cap == alt_blk.no_slots) # true if there is overflow
        block_of = not alt_blk.has_capacity() # true if there is overflow
        if verbose:
            print(f"alternate g_bucket is {alternate_bucket}")
            print(f"alternate block is {alternate_bucket//self.no_buckets}")
            print(f"alternate lbi is: {alt_lbi} of capacity {alt_cap}")
            print(f"bucket overflow: {bucket_of}, block overflow: {block_of}")
            print("+-+-+-+-+-+-+-+-")
        return ((not bucket_of) and (not block_of))

    def remove_and_replace(self,old_blk, gbucket_index1, gbucket_index2, old_fp, new_fp,simple=True, same_bucket=True,verbose=False):
        """Places old_fp at its alternate bucket(and block), sets the OTA in the old_blk and puts new_fp in its place."""
        """"Flags:
            simple: True if we have one level eviction, False if we have multiple level eviction
            same_bucket: True if we have a bucket overflow, False if it is a block overflow
        """
        success = False
        # gbucket_index1 is the bucket that the old_fp maps to
        # gbucket_index2 is the bucket that the new_fp maps to
        # if the evicted is from the same bucket, these indices are the same
        # if they are different, we delete the old_fp from gbucket_index1
        # and insert the new_fp to gbucket_index2
        lbi = gbucket_index1 % self.no_buckets
        old_blk = self.Blocks[gbucket_index1//self.no_buckets]
        old_blk.set_OTA(lbi) # set the OTA bit
        # put old_fp to its alternate bucket
        alt_bucket = self.h_prime(gbucket_index1,old_fp)
        alt_blk = self.Blocks[alt_bucket//self.no_buckets]
        alt_lbi = alt_bucket % self.no_buckets
        if (simple):
            # if the alt bucket or block does not have space, we need to not copy over
            # the old_fp, but instead use it in the calling function in the while loop
            alt_blk.table_simple_store(alt_lbi,old_fp)
        # normally we'd use the code for the delete function
        # for now we copy code from Block.read_and_cmp to find the old_fp in the old_blk and overwrite it with new_fp
        offset = 0
        bits = old_blk.fca_bits
        fp_size = old_blk.fp_size
        bucket_cap = old_blk.bucket_capacity(lbi)
        for i in range(lbi):
            cap = old_blk.bucket_capacity(i)
            offset += cap
        for i in range(bucket_cap): # find the index of the old_fp
            index = offset + i
            item = old_blk.fsa[index*fp_size:(index+1)*fp_size]
            if (item==old_fp):
                success = True
                if (same_bucket):
                    # if the two fingerprints are in the same bucket we simply overwrite old with the new
                    old_blk.fsa.overwrite(BitArray(new_fp),index*fp_size)
                else: # if it is not in the same bucket, we need gbucket_index2 
                    # first we need to delete old_fp from block
                    # we have the index, so we just shift to the left by fp_size
                    old_blk.fsa[(index)*fp_size::] <<= fp_size
                    # we also need to decrement old_fp bucket capacity
                    old_blk.fca.overwrite(BitArray(fill_bits(bucket_cap-1,bits)),lbi*bits)
                    # then we add the new_fp to its respective bucket
                    lbi2 = gbucket_index2 % self.no_buckets
                    old_blk.table_simple_store(lbi2,new_fp)
                break
        if (not success):
            print('error in remove_and_replace')
        return success
    
    def res_conflict(self,blk1,lbi1,fp,verbose=False):
        # we want to insert fp in its blk1 and lbi1 position
        max_count = 8000 # max times we can try evicting a fingerprint
        count = 0 # current count
        evicted = False
        fp = BitArray(fp)
        while(count<max_count and not evicted):
            cap1 = blk1.bucket_capacity(lbi1)
            candidates = []
            if (cap1 == blk1.no_slots):
                # we have a bucket overflow
                # candidate bucket to evict is from the specific bucket
                offset_fp = 0 # offset (in # of fingerprints) in the blk1.fsa
                glbi1 = blk1.no*self.no_buckets + lbi1
                for i in range(lbi1): # count how many fingerprints the buckets before have stored
                    cap = blk1.bucket_capacity(i)
                    offset_fp += cap
                # offset = offset_fp*fp_size # offset (in bits) in the blk1.fsa
                for i in range(cap1):
                    candidates.append(blk1.fsa[(offset_fp+i)*blk1.fp_size:(offset_fp+i+1)*blk1.fp_size]) # append the candidate fingerprint
                # check if a fingerprint can go to its alternate bucket
                for c in candidates:
                    if (self.check_candidate_bucket(glbi1,c)):
                        evicted = True
                        glbi2 = self.h_prime(glbi1, c)
                        self.remove_and_replace(blk1,glbi1,glbi2,c,fp)
                        break
                if (not(evicted)): 
                    # all candidate buckets were full, pick a candidate at random
                    # moreover, we need to run the while loop again because the old_fp will need to
                    # evict another fingerprint to go into its alternate bucket
                    # so the old_fp becomes new_fp and the "another fingerprint" becomes the old_fp
                    c = BitArray(random.choice(candidates))
                    self.remove_and_replace(blk1,glbi1,glbi1,c,fp,simple=False) 
                    # this does not copy the old_fp to its secondary bucket
                    # we keep it to  run the while loop again
                    fp = c # new_fp = old_fp
                    glbi2 = self.h_prime(glbi1,fp) # this is the alternate (global) bucket
                    lbi1 = glbi2 % self.no_buckets # this is the alternate (local) bucket
                    blk1 = self.Blocks[glbi2//self.no_buckets] # this is the alternate block
            else: 
                # we have a block overflow (and not a bucket overflow)
                # candidate bucket to evict is from the specific block
                glbi2 = blk1.no*self.no_buckets + lbi1 # the bucket the fp maps to 
                # (not necessarily the one from which we evict a fingerprint)
                pointer = 0 # a pointer to traverse the fsa
                for bucket in range(self.no_buckets): 
                # we need to have both fingerprints and their buckets to get their alternate bucket
                # so we check each bucket
                    cap = blk1.bucket_capacity(bucket)
                    for i in range(cap): # add the fingerprints (if cap !=0) to candidates[]
                        index = pointer + i # it's the fp index (not bit index)
                        if (index!=blk1.no_fingerprints): # if we are not at the end of fsa
                            f = blk1.fsa[(index)*blk1.fp_size:(index + 1)*blk1.fp_size] # fp is a BitArray
                            candidates.append((bucket,f))
                    if (pointer + cap <= blk1.no_fingerprints):
                        pointer += cap # proceed to next bucket
                # we should have blk1.no_fingerprints in candidates[]
                # check if a fingerprint can go to its alternate bucket
                if (len(candidates) != blk1.no_fingerprints):
                    print("error in loading eviction candidates from block")
                for b,old_fp in candidates:
                    glbi1 = blk1.no*self.no_buckets + b # glbi of the old_fp
                    if (self.check_candidate_bucket(glbi1,old_fp)): # if candidate buckets has enough slots
                        evicted = True
                        self.remove_and_replace(blk1, glbi1, glbi2, old_fp,fp, same_bucket=False)
                        break
                if (not(evicted)):
                    # all candidate buckets were full, pick a candidate at random
                    # moreover, we need to run the while loop again because the old_fp will need to
                    # evict another fingerprint to go into its alternate bucket
                    # so the old_fp becomes new_fp and the "another fingerprint" becomes the old_fp
                    b,c = random.choice(candidates)
                    glbi1 = blk1.no*self.no_buckets + b # glbi of the old_fp
                    # just write the new_fp and delete the old, without writing the old in its alternate location
                    c = BitArray(c)
                    self.remove_and_replace(blk1,glbi1,glbi2,c,fp,simple=False,same_bucket=False)
                    # at this point we need to insert c at its alternate location by another eviction
                    # so we run the loop again with different old_fp and fp
                    fp = c
                    glbi2 = self.h_prime(glbi1,fp) # this is the alternate (global) bucket
                    lbi1 = glbi2 % self.no_buckets # this is the alternate (local) bucket
                    blk1 = self.Blocks[glbi2//self.no_buckets] # this is the alternate block
            count+=1
        if (count > 75):
            print(f"eviction counter > 75, counter = {count}")
        if (count == max_count):
            raise Exception('eviction error') # in most cases we haven't created enough blocks for all items
            # no_blocks*no_fingerprints > no_items
        return

    def check(self,item,verbose=False):
        fp = fingerprint(item,self.fingerprint_size)
        glbi1 = self.h1(item)
        block1 = self.Blocks[glbi1//self.no_buckets]
        lbi1 = glbi1 % self.no_buckets
        ota_bit = block1.get_OTA(lbi1)
        if verbose:
            print(f"fp = {(int(fp,2))}, block1 = {glbi1//self.no_buckets} lbi1 = {lbi1}, ota_bit = {ota_bit}")
        match = block1.read_and_cmp(lbi1, fp, verbose)
        if (match or not(ota_bit)):
            if (match and verbose):
                print(f"found fp = {(int(fp,2))} at block {glbi1//self.no_buckets} and bucket {lbi1}")
            return match
        else:
            glbi2 = self.h2(item)
            block2 = self.Blocks[glbi2//self.no_buckets]
            lbi2 = glbi2 % self.no_buckets
            if verbose:
                print(f"fp = {(int(fp,2))}, block2 = {glbi2//self.no_buckets} lbi2 = {lbi2}")
            match = block2.read_and_cmp(lbi2, fp, verbose) 
            if (match and verbose):
                print(f"found fp = {(int(fp,2))} at block {glbi2//self.no_buckets} and bucket {lbi2}")    
            return match
    
    def printFilter(self):
        for i,blk in enumerate(self.Blocks):
            print('Block #',i)
            blk.print_whole_block()
            print('########################')

    def serialize(self):
        """Returns the whole filter as a string."""
        s = ""
        for block in self.Blocks:
            s = s + block.serialize() + '\n'
        return s

def fill_filter(filename,filter):
    pass

# testing
if __name__ == '__main__':
    matchAll = True
    verbose = True
    filter = MortonFilter(458)
    for i in range(20000):
        # filter.insert("item"+str(i),verbose=True)
        filter.insert("item"+str(i))
    start = time.time()
    for i in range(20000):
        match = filter.check("item"+str(i))
        matchAll &= match # must be True (no false negatives)
        if (not(match)):
            print("query failed for: item"+str(i))
            break
    end = time.time()
    print(matchAll)



    print("time elapsed:", end - start)
    print("program ended")