from django.conf import settings
import rpyc

def rpyc_lib():
    remote = rpyc.connect("localhost", settings.MY_LIB_RPC_PORT,
                    config={"allow_all_attrs": True}).root
    remote.update()
