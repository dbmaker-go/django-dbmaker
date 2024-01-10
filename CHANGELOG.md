## 2.2.17.15 (2024-01-10)


### Bug Fixes

* **base.py:** ERROE(23000) referential constraint violation :
                 Modify check_constraints() to check constraints by setting fkchk to True. Return False afterward.
([48b9d20](https://github.com/dbmaker-go/django-dbmaker/commit/48b9d204c7881bca2400753e9a00a0aedc7b5b27))



## 2.2.17.14 (2023-10-11)


### Bug Fixes

* **base.py:** ERROE(6130) for concat bigserial type:
                 Concat does not support numeric parameter in DBMaker.
                 So add set itcmd on in the connection, it will be executed successfully
([6f04782](https://github.com/dbmaker-go/django-dbmaker/commit/6f04782fd60915d68051a7f7fac4665f42761ef8))



## 2.2.17.13 (2023-04-11)


### Bug Fixes

* **base.py:** Add option SELTMPBB in setttings.py:
                 If you set it to Ture, you can establish a connection to:
                   call SETSYSTEMOPTION('SELTMPBB', '1');
                   SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;
                 If you don't set it or set it to False, just as it is:
                   SET TRANSACTION ISOLATION LEVEL READ COMMITTED;
([e1522d3](https://github.com/dbmaker-go/django-dbmaker/commit/e1522d355f692357d4e21b50f0cc2ddee39b84af))



## 2.2.17.12 (2023-04-03)


### Bug Fixes

* **schema.py:** For journal full in alter table:
                   Avoid the occurrence of Journal full due to alter table/select into during migration when the table is particularly large, adding auto commit for every 100 tuples (set selinto commit 100)
([d8afb6b](https://github.com/dbmaker-go/django-dbmaker/commit/d8afb6bdd517e3a9965776b2cb8640f1a8ac99f6))



## 2.2.17.11 (2023-02-17)


### Features

* **base.py:** Add sql statement and parameter in log file£º
                 Add ability to print SQL statements and parameter to log files when DBMaker returns error
([f1622b5](https://github.com/dbmaker-go/django-dbmaker/commit/f1622b515d24f69107e3db2b8fc80a88e1246b47))