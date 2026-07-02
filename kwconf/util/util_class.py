class class_or_instancemethod(classmethod):
    """
    A decorator that allows a method to behave as a class or instance method.

    The user is responsible for testing if the first argument is an instance of
    the class or the class itself. This is can be done by using
    ``isinstance(..., type)``. More explicitly, if the first argument of the
    decorated function is ``self_or_cls``, then ``isinstance(self_or_cls,
    type)`` returns True if the function is behaving as a classmethod and False
    if it is an instance method.

    This code is derived from [SO28237955]_.

    References:
        .. [SO28237955] https://stackoverflow.com/questions/28237955/same-name-for-classmethod-and-instancemethod

    Example:
        >>> class X:
        ...     @class_or_instancemethod
        ...     def foo(self_or_cls):
        ...         if isinstance(self_or_cls, type):
        ...             return f"bound to the class"
        ...         else:
        ...             return f"bound to the instance"
        >>> print(X.foo())
        bound to the class
        >>> print(X().foo())
        bound to the instance
    """

    def __get__(self, instance, owner=None):
        """
        Descriptor method

        References:
            https://docs.python.org/3/reference/datamodel.html#object.__get__
        """
        if instance is None:
            descr_get = super().__get__
        else:
            descr_get = self.__func__.__get__  # type: ignore
        return descr_get(instance, owner)
